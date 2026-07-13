#!/usr/bin/env python3
"""Poll 1xBet Get1x2_VZip and import odds to PostgreSQL (place=line)."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from dataclasses import replace

import requests

from adapters.base import ChangeType
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect
from lxbet_line.api import LxbetLineApiError, fetch_snapshot, packet_version
from lxbet_line.config import (
    DEFAULT_SITE_NAME,
    LxbetLineConfig,
    normalize_site_name,
)
from lxbet_line.mapper import map_packet_to_changes, packet_summary

logger = logging.getLogger(__name__)

OTHER_BOOKMAKER_SITES = frozenset(
    {"fonbet.com", "bet365.com", "ligastavok.ru", "betcity.ru"}
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
    api_config: LxbetLineConfig,
    db_config: DatabaseConfig,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    site_name = resolve_site_name(None, db_config.site_name)
    if api_config.site_name:
        site_name = normalize_site_name(api_config.site_name)
    db_config = replace(db_config, site_name=site_name)

    iteration = 0
    consecutive_failures = 0

    print(f"Polling every {api_config.poll_interval}s -> PostgreSQL ({site_name})")
    if api_config.fetch_all_sports:
        print(f"  sports: {api_config.sports_list_url()}")
        print(
            f"  mode: all sports (cap {api_config.sport_count}/request, "
            f"workers={api_config.max_workers}"
            + (
                f", only={sorted(api_config.only_sport_ids)}"
                if api_config.only_sport_ids
                else ""
            )
            + ")"
        )
    else:
        print(f"  snapshot: {api_config.snapshot_url()}")
    if api_config.fetch_top:
        print(f"  top: {api_config.top_url()}")
    print(f"  place: line")

    with connect(db_config) as conn:
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            try:
                packet_result = fetch_snapshot(api_config)
                packet = packet_result.packet
                version = packet_version(packet)
                changes = map_packet_to_changes(packet, version=version)
                summary = packet_summary(packet, version=version)

                fixture_ids = {
                    c.match_payload_id
                    for c in changes
                    if c.change_type == ChangeType.FIXTURE
                }
                # Incomplete fetches must not wipe previously saved recent rows.
                coverage_ok = (
                    packet_result.coverage >= api_config.prune_coverage_min
                )
                prune_absent = coverage_ok and bool(fixture_ids)
                if not coverage_ok:
                    logger.info(
                        "Skip absent prune (coverage=%.0f%% < %.0f%%, "
                        "fetched=%s catalog=%s) — keeping recent DB rows",
                        packet_result.coverage * 100,
                        api_config.prune_coverage_min * 100,
                        packet_result.fetched_events,
                        packet_result.expected_events,
                    )

                snapshot_id, counts = apply_changes(
                    conn,
                    changes,
                    site_name=site_name,
                    packet_version=version,
                    source_file=api_config.sports_list_url()
                    if api_config.fetch_all_sports
                    else api_config.snapshot_url(),
                    retain_snapshot_years=0,
                    prune_absent=prune_absent,
                    active_match_ids=fixture_ids if prune_absent else None,
                    prune_place="line",
                    retain_snapshot_count=1,
                    prune_past_hours=api_config.prune_past_hours or None,
                )
                consecutive_failures = 0

                by_type = Counter(c.change_type.value for c in changes)
                print(
                    f"[{iteration}] version={version} snapshot={snapshot_id} "
                    f"fixtures={summary.fixtures} odds_markets={summary.odds_markets} "
                    f"coverage={packet_result.coverage:.0%} "
                    f"prune_absent={prune_absent} "
                    f"changes={dict(by_type)} "
                    f"db_matches={counts['matches']} db_odds={counts['odds_lines']} "
                    f"pruned_matches={counts.get('matches_deleted', 0)} "
                    f"pruned_snapshots={counts.get('snapshots_deleted', 0)}"
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

                if _is_transient_network_error(exc) or isinstance(
                    exc, LxbetLineApiError
                ):
                    logger.warning(
                        "1xBet line poll iteration %s failed: %s",
                        iteration,
                        exc,
                    )
                else:
                    logger.exception(
                        "1xBet line poll iteration %s failed: %s",
                        iteration,
                        exc,
                    )
                print(
                    f"[{iteration}] ERROR: {exc} "
                    f"(failures={consecutive_failures})"
                )
                backoff = min(
                    api_config.poll_interval
                    * (2 ** min(max(consecutive_failures, 1), 4)),
                    60.0,
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
        description="Poll 1xBet Get1x2_VZip into PostgreSQL (place=line).",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="DB site name (default: 1xbet.com)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: 3.5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single snapshot import",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print a few sample fixtures each tick",
    )
    args = parser.parse_args()

    api_config = LxbetLineConfig.from_env()
    overrides: dict = {}
    if args.site_name:
        overrides["site_name"] = normalize_site_name(args.site_name)
    if args.interval is not None:
        overrides["poll_interval"] = args.interval
    if overrides:
        api_config = replace(api_config, **overrides)

    db_config = DatabaseConfig.from_env()
    db_config = replace(
        db_config,
        site_name=resolve_site_name(args.site_name, db_config.site_name),
    )

    run_poll(
        api_config=api_config,
        db_config=db_config,
        max_iterations=1 if args.once else None,
        show_samples=args.samples,
    )


if __name__ == "__main__":
    main()
