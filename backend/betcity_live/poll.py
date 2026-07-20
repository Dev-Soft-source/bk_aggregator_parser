#!/usr/bin/env python3
"""Poll Betcity live feed and import odds to PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from dataclasses import replace

from adapters.base import ChangeType
from betcity_live.adapter import BetcityAdapter
from betcity_live.cleanup_sites import cleanup_alias_sites
from betcity_live.config import (
    DEFAULT_SITE_NAME,
    BetcityConfig,
    normalize_proxy,
    normalize_site_name,
)
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect

logger = logging.getLogger(__name__)

OTHER_BOOKMAKER_SITES = frozenset(
    {"fonbet.com", "bet365.com", "ligastavok.ru"}
)


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def resolve_site_name(requested: str | None, env_site_name: str | None) -> str:
    """
    Canonical Betcity site for DB writes.

    - Explicit --site-name wins (after alias normalization)
    - Env SITE_NAME from another bookmaker is ignored
    - Truncated aliases like `betcity.` map to `betcity.ru`
    """
    if requested:
        return normalize_site_name(requested)
    env_name = (env_site_name or "").strip()
    if not env_name or env_name in OTHER_BOOKMAKER_SITES:
        return DEFAULT_SITE_NAME
    return normalize_site_name(env_name)


def _print_summary(
    iteration: int,
    summary,
    changes,
    chunks: int,
    counts: dict[str, int] | None = None,
    *,
    catalog_size: int = 0,
) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    named = sum(
        1
        for c in changes
        if c.change_type == ChangeType.FIXTURE
        and not str(c.payload.get("team1") or "").startswith("Event ")
    )
    extra = ""
    if counts:
        extra = (
            f" db_matches={counts['matches']} db_scores={counts['scores_updated']} "
            f"db_odds={counts['odds_lines']}"
        )
        if counts.get("matches_deleted"):
            extra += f" pruned_matches={counts['matches_deleted']}"
        if counts.get("snapshots_deleted"):
            extra += f" pruned_snapshots={counts['snapshots_deleted']}"
    print(
        f"[{iteration}] ws_chunks={chunks} catalog={catalog_size} named={named} "
        f"fixtures={summary.fixtures} scores={summary.score_changes} "
        f"odds_markets={summary.odds_markets} outcomes={summary.odds_outcomes} "
        f"changes={dict(by_type)}{extra}"
    )


def run_poll(
    *,
    api_config: BetcityConfig,
    db_config: DatabaseConfig,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    site_name = normalize_site_name(db_config.site_name) or DEFAULT_SITE_NAME
    if site_name in OTHER_BOOKMAKER_SITES:
        site_name = DEFAULT_SITE_NAME
    db_config = replace(db_config, site_name=site_name)
    adapter = BetcityAdapter(api_config)
    try:
        with connect(db_config) as conn:
            cleanup = cleanup_alias_sites(conn, canonical=site_name)
            if cleanup.get("aliases_found"):
                print(f"Cleaned alias sites: {cleanup}")

        adapter.start()
        print(f"Polling every {api_config.poll_interval}s -> PostgreSQL ({site_name})")
        if api_config.use_browser:
            print(f"  mode: browser tap (CDP {api_config.browser_cdp_url})")
            print(f"  page: {api_config.browser_url}")
        else:
            print(f"  mode: direct WebSocket")
            print(f"  ws: {api_config.ws_url}")
        if api_config.proxy:
            print(f"  proxy: {api_config.proxy}")
        print(f"  catalog: {api_config.catalog_url} ({adapter.catalog.size} events)")

        iteration = 0
        with connect(db_config) as conn:
            for _packet, changes, summary in adapter.stream_poll_changes(
                max_iterations=max_iterations
            ):
                iteration += 1
                try:
                    # Only keep matches we actually export this tick.
                    # Blocked / unnamed / finished rows are omitted here and pruned.
                    active_ids = {
                        c.match_payload_id
                        for c in changes
                        if c.change_type == ChangeType.FIXTURE
                    }
                    snapshot_id, counts = apply_changes(
                        conn,
                        changes,
                        site_name=site_name,
                        packet_version=int(time.time()),
                        source_file="betcity poll",
                        retain_snapshot_years=db_config.retain_snapshot_years,
                        prune_absent=bool(active_ids),
                        active_match_ids=active_ids,
                    )
                except Exception as exc:
                    logger.warning("DB import iteration %s failed: %s", iteration, exc)
                    _print_summary(
                        iteration,
                        summary,
                        changes,
                        0,
                        None,
                        catalog_size=adapter.catalog.size,
                    )
                    continue

                if show_samples:
                    shown = 0
                    for change in changes:
                        if change.change_type != ChangeType.FIXTURE:
                            continue
                        _safe_print(
                            f"  sample fixture id={change.match_payload_id}: "
                            f"{change.payload.get('team1')} vs {change.payload.get('team2')} "
                            f"[{change.payload.get('league_name')}]"
                        )
                        shown += 1
                        if shown >= 3:
                            break
                    for change in changes:
                        if change.change_type != ChangeType.ODDS:
                            continue
                        op = change.payload.get("outcomes") or []
                        odds = ", ".join(
                            f"{o.get('factor_id')}={o.get('odds')}" for o in op
                        )
                        _safe_print(
                            f"  sample odds id={change.match_payload_id}: {odds}"
                        )
                        break

                _print_summary(
                    iteration,
                    summary,
                    changes,
                    adapter._last_chunks,
                    counts,
                    catalog_size=adapter.catalog.size,
                )
                logger.debug("snapshot_id=%s", snapshot_id)
    finally:
        adapter.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Betcity live feed and import to PostgreSQL.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default BETCITY_POLL_INTERVAL_SECONDS or 3.5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="Override SITE_NAME (aliases like betcity. normalize to betcity.ru)",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print sample fixtures/odds each iteration",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help=argparse.SUPPRESS,  # default; kept for backward compatibility
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Force direct Python WebSocket (no Chrome)",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy host:port (or http://host:port) for catalog + Chrome launcher env",
    )
    args = parser.parse_args()

    api_config = BetcityConfig.from_env()
    # Default to CDP Chrome like Bet365; use --direct for Python WebSocket.
    overrides: dict = {"use_browser": True}
    if args.interval is not None:
        overrides["poll_interval"] = args.interval
    if args.direct:
        overrides["use_browser"] = False
    elif args.browser:
        overrides["use_browser"] = True
    if args.proxy is not None:
        overrides["proxy"] = normalize_proxy(args.proxy)
    api_config = replace(api_config, **overrides)

    db_config = DatabaseConfig.from_env()
    site_name = resolve_site_name(args.site_name, db_config.site_name)
    db_config = replace(db_config, site_name=site_name)

    run_poll(
        api_config=api_config,
        db_config=db_config,
        max_iterations=1 if args.once else None,
        show_samples=args.samples,
    )


if __name__ == "__main__":
    main()
