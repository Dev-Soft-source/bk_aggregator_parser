#!/usr/bin/env python3
"""Poll Betcity prematch /d/off/events and import odds to PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from dataclasses import replace

import requests

from adapters.base import ChangeType
from betcity_line.api import (
    BetcityLineApiError,
    fetch_delta,
    fetch_snapshot,
    packet_ntime,
)
from betcity_line.config import (
    DEFAULT_SITE_NAME,
    BetcityLineConfig,
    normalize_site_name,
)
from betcity_line.mapper import map_state_to_changes, state_summary
from betcity_line.state import BetcityLineState
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect

logger = logging.getLogger(__name__)

OTHER_BOOKMAKER_SITES = frozenset(
    {"fonbet.com", "bet365.com", "ligastavok.ru"}
)


def resolve_site_name(requested: str | None, env_site_name: str | None) -> str:
    if requested:
        return normalize_site_name(requested)
    env_name = (env_site_name or "").strip()
    if not env_name or env_name in OTHER_BOOKMAKER_SITES:
        return DEFAULT_SITE_NAME
    return normalize_site_name(env_name)


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _is_transient_network_error(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.SSLError,
        ),
    )


def run_poll(
    *,
    api_config: BetcityLineConfig,
    db_config: DatabaseConfig,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    site_name = resolve_site_name(None, db_config.site_name)
    if api_config.site_name:
        site_name = normalize_site_name(api_config.site_name)
    db_config = replace(db_config, site_name=site_name)

    state = BetcityLineState()
    ntime: int | None = None
    iteration = 0
    consecutive_failures = 0

    print(f"Polling every {api_config.poll_interval}s -> PostgreSQL ({site_name})")
    print(f"  snapshot: {api_config.snapshot_url()}")
    print(
        f"  timeout: connect={api_config.connect_timeout}s read={api_config.timeout}s"
    )
    print(f"  place: line")

    with connect(db_config) as conn:
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            had_md = ntime is not None
            try:
                if ntime is None:
                    packet = fetch_snapshot(api_config)
                    source = api_config.snapshot_url()
                    state.apply_packet(packet, replace=True)
                else:
                    packet = fetch_delta(ntime, api_config)
                    source = api_config.delta_url(ntime)
                    state.apply_packet(packet, replace=False)

                new_ntime = packet_ntime(packet)
                if new_ntime is None:
                    raise BetcityLineApiError("Response missing reply.ntime")

                version = int(new_ntime)
                changes = map_state_to_changes(state, version=version)
                summary = state_summary(state)

                fixture_ids = {
                    c.match_payload_id
                    for c in changes
                    if c.change_type == ChangeType.FIXTURE
                }
                prune = (not had_md) and bool(fixture_ids)

                snapshot_id, counts = apply_changes(
                    conn,
                    changes,
                    site_name=site_name,
                    packet_version=version,
                    source_file=source,
                    retain_snapshot_years=0,
                    prune_absent=prune,
                    active_match_ids=fixture_ids if prune else None,
                    prune_place="line",
                    retain_snapshot_count=1,
                )
                ntime = new_ntime
                consecutive_failures = 0

                by_type = Counter(c.change_type.value for c in changes)
                print(
                    f"[{iteration}] ntime={ntime} snapshot={snapshot_id} "
                    f"fixtures={summary.fixtures} odds_markets={summary.odds_markets} "
                    f"changes={dict(by_type)} "
                    f"db_matches={counts['matches']} db_odds={counts['odds_lines']} "
                    f"pruned_matches={counts.get('matches_deleted', 0)} "
                    f"pruned_snapshots={counts.get('snapshots_deleted', 0)}"
                    + (f" md={ntime}" if had_md else " (snapshot)")
                )

                if show_samples:
                    shown = 0
                    for change in changes:
                        if change.change_type != ChangeType.FIXTURE:
                            continue
                        _safe_print(
                            f"  sample id={change.match_payload_id}: "
                            f"{change.payload.get('team1')} vs {change.payload.get('team2')} "
                            f"[{change.payload.get('league_name')}]"
                        )
                        shown += 1
                        if shown >= 3:
                            break
            except Exception as exc:
                consecutive_failures += 1
                try:
                    conn.rollback()
                except Exception:
                    logger.exception("Rollback after poll failure failed")

                transient = _is_transient_network_error(exc)
                force_reset = (
                    not transient
                    or ntime is None
                    or consecutive_failures >= api_config.reset_after_failures
                )

                if transient:
                    logger.warning(
                        "Betcity line poll iteration %s network error: %s",
                        iteration,
                        exc,
                    )
                else:
                    logger.exception(
                        "Betcity line poll iteration %s failed: %s",
                        iteration,
                        exc,
                    )

                if force_reset:
                    print(
                        f"[{iteration}] ERROR: {exc} — "
                        f"resetting with snapshot on next tick "
                        f"(failures={consecutive_failures})"
                    )
                    ntime = None
                    state.clear()
                    failures_for_backoff = consecutive_failures
                    consecutive_failures = 0
                else:
                    print(
                        f"[{iteration}] ERROR: {exc} — "
                        f"keeping md={ntime}, retry delta "
                        f"(failures={consecutive_failures}/"
                        f"{api_config.reset_after_failures})"
                    )
                    failures_for_backoff = consecutive_failures

                backoff = min(
                    api_config.poll_interval
                    * (2 ** min(max(failures_for_backoff, 1), 4)),
                    api_config.max_backoff,
                )
                if max_iterations is not None and iteration >= max_iterations:
                    break
                time.sleep(backoff)
                continue

            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(api_config.poll_interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Betcity prematch /d/off/events into PostgreSQL.",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="DB site name (default: betcity.ru)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="HTTP read timeout seconds (default: 90)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run snapshot + one md delta only",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print a few sample fixtures each tick",
    )
    args = parser.parse_args()

    api_config = BetcityLineConfig.from_env()
    overrides: dict = {}
    if args.site_name:
        overrides["site_name"] = normalize_site_name(args.site_name)
    if args.interval is not None:
        overrides["poll_interval"] = args.interval
    if args.timeout is not None:
        overrides["timeout"] = args.timeout
    if overrides:
        api_config = replace(api_config, **overrides)

    db_config = DatabaseConfig.from_env()
    db_config = replace(
        db_config,
        site_name=resolve_site_name(args.site_name, db_config.site_name),
    )

    max_iter = 2 if args.once else None
    run_poll(
        api_config=api_config,
        db_config=db_config,
        max_iterations=max_iter,
        show_samples=args.samples,
    )


if __name__ == "__main__":
    main()
