#!/usr/bin/env python3
"""Poll Bet365 ZAP browser feed and import odds to PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from dataclasses import replace

from adapters.base import ChangeType
from bet365.adapter import Bet365Adapter
from bet365.config import Bet365Config
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect

logger = logging.getLogger(__name__)


def _print_summary(
    iteration: int,
    summary,
    changes,
    chunks: int,
    counts: dict[str, int] | None = None,
) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    extra = ""
    if counts:
        pruned = counts.get("matches_deleted", 0)
        extra = (
            f" db_matches={counts['matches']} db_scores={counts['scores_updated']} "
            f"db_odds={counts['odds_lines']}"
        )
        if pruned:
            extra += f" pruned_finished={pruned}"
    print(
        f"[{iteration}] zap_chunks={chunks} "
        f"fixtures={summary.fixtures} scores={summary.score_changes} "
        f"odds_markets={summary.odds_markets} outcomes={summary.odds_outcomes} "
        f"changes={dict(by_type)}{extra}"
    )


def run_poll(
    *,
    api_config: Bet365Config,
    db_config: DatabaseConfig,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    adapter = Bet365Adapter(api_config)
    try:
        adapter.start()
        print(f"Polling every {api_config.poll_interval}s -> PostgreSQL ({db_config.site_name})")
        print(f"  browser: CDP {api_config.browser_cdp_url}")
        print(f"  entry: {api_config.browser_entry_url}")
        print(f"  live hub: {api_config.browser_url}")
        if api_config.safe_mode:
            print(
                f"  safe mode: poll={api_config.poll_interval}s, "
                f"auto_reload={api_config.browser_auto_reload}, "
                f"recover_reload={api_config.recover_reload}"
            )
        if api_config.wait_for_cloudflare:
            auto = (
                f", auto-click after {api_config.cloudflare_auto_click_delay_seconds:.0f}s"
                if api_config.cloudflare_auto_click
                else ", manual only"
            )
            print(
                f"  cloudflare: wait up to {api_config.cloudflare_wait_seconds:.0f}s{auto}"
            )
        if api_config.poll_live_only:
            print("  filter: live in-play only (FS=1)")

        iteration = 0
        with connect(db_config) as conn:
            for _packet, changes, summary in adapter.stream_poll_changes(
                max_iterations=max_iterations
            ):
                iteration += 1
                try:
                    # Keep DB live set aligned with current export — drop finished
                    # matches that left the ZAP feed / lost open odds.
                    active_ids = {
                        c.match_payload_id
                        for c in changes
                        if c.change_type == ChangeType.FIXTURE
                        and (c.payload or {}).get("place") == "live"
                    }
                    snapshot_id, counts = apply_changes(
                        conn,
                        changes,
                        site_name=db_config.site_name,
                        packet_version=int(time.time()),
                        source_file="bet365 poll",
                        retain_snapshot_years=db_config.retain_snapshot_years,
                        prune_absent=bool(active_ids),
                        active_match_ids=active_ids,
                        prune_place="live",
                    )
                except Exception as exc:
                    logger.warning("DB import iteration %s failed: %s", iteration, exc)
                    _print_summary(iteration, summary, changes, 0, None)
                    continue

                if show_samples:
                    for change in changes[:5]:
                        if change.change_type == ChangeType.ODDS:
                            op = change.payload.get("outcomes") or []
                            odds = ", ".join(
                                f"{o.get('factor_id')}={o.get('line_param_text') or o.get('odds')}"
                                for o in op
                            )
                            print(f"  sample odds fi={change.match_payload_id}: {odds}")

                _print_summary(iteration, summary, changes, adapter._last_chunks, counts)
                logger.debug("snapshot_id=%s", snapshot_id)
    finally:
        adapter.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Bet365 in-play ZAP feed via CDP Chrome and import to PostgreSQL.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: 8s safe mode, 3.5s otherwise)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Import live in-play matches only",
    )
    parser.add_argument(
        "--all-matches",
        action="store_true",
        help="Include prematch line (default: all with 1X2 odds)",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print sample odds lines each iteration",
    )
    args = parser.parse_args()

    api_config = Bet365Config.from_env()
    overrides: dict = {"use_browser": True}
    if args.interval is not None:
        overrides["poll_interval"] = args.interval
    if args.live_only:
        overrides["poll_live_only"] = True
    if args.all_matches:
        overrides["poll_live_only"] = False
    if overrides:
        api_config = replace(api_config, **overrides)

    db_config = DatabaseConfig.from_env()
    run_poll(
        api_config=api_config,
        db_config=db_config,
        max_iterations=1 if args.once else None,
        show_samples=args.samples,
    )


if __name__ == "__main__":
    main()
