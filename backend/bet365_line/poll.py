#!/usr/bin/env python3
"""Poll Bet365 prematch ZAP feed (#/AO/) and import odds to PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from dataclasses import replace

from adapters.base import ChangeType
from bet365_line.adapter import Bet365LineAdapter
from bet365_line.config import (
    DEFAULT_SITE_NAME,
    line_config_from_env,
    line_prune_absent_from_env,
)
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
            extra += f" pruned_absent={pruned}"
    print(
        f"[{iteration}] zap_chunks={chunks} "
        f"fixtures={summary.fixtures} scores={summary.score_changes} "
        f"odds_markets={summary.odds_markets} outcomes={summary.odds_outcomes} "
        f"changes={dict(by_type)}{extra}"
    )


def run_poll(
    *,
    api_config,
    db_config: DatabaseConfig,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    site_name = (db_config.site_name or "").strip() or DEFAULT_SITE_NAME
    db_config = replace(db_config, site_name=site_name)
    adapter = Bet365LineAdapter(api_config)
    try:
        adapter.start()
        print(
            f"Polling Bet365 line every {api_config.poll_interval}s "
            f"-> PostgreSQL ({site_name})"
        )
        print(f"  browser: CDP {api_config.browser_cdp_url}")
        print(f"  entry: {api_config.browser_entry_url}")
        print(f"  line hub: {api_config.browser_url}")
        print("  place: line")
        prune_absent = line_prune_absent_from_env()
        print(f"  prune_absent: {prune_absent}")
        if api_config.safe_mode:
            print(
                f"  safe mode: poll={api_config.poll_interval}s, "
                f"auto_reload={api_config.browser_auto_reload}, "
                f"recover_reload={api_config.recover_reload}"
            )

        iteration = 0
        prune_absent = line_prune_absent_from_env()
        with connect(db_config) as conn:
            for _packet, changes, summary in adapter.stream_poll_changes(
                max_iterations=max_iterations
            ):
                iteration += 1
                try:
                    active_ids = {
                        c.match_payload_id
                        for c in changes
                        if c.change_type == ChangeType.FIXTURE
                        and (c.payload or {}).get("place") == "line"
                    }
                    snapshot_id, counts = apply_changes(
                        conn,
                        changes,
                        site_name=site_name,
                        packet_version=int(time.time()),
                        source_file="bet365-line poll",
                        retain_snapshot_years=db_config.retain_snapshot_years,
                        prune_absent=prune_absent and bool(active_ids),
                        active_match_ids=active_ids if prune_absent else set(),
                        prune_place="line",
                    )
                except Exception as exc:
                    logger.warning(
                        "DB import iteration %s failed: %s", iteration, exc
                    )
                    _print_summary(iteration, summary, changes, 0, None)
                    continue

                if show_samples:
                    for change in changes[:5]:
                        if change.change_type == ChangeType.ODDS:
                            op = change.payload.get("outcomes") or []
                            odds = ", ".join(
                                f"{o.get('factor_id')}="
                                f"{o.get('line_param_text') or o.get('odds')}"
                                for o in op
                            )
                            print(
                                f"  sample odds fi={change.match_payload_id}: {odds}"
                            )

                _print_summary(
                    iteration, summary, changes, adapter._last_chunks, counts
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
        description=(
            "Poll Bet365 prematch ZAP feed via CDP Chrome (#/AO/) "
            "and import to PostgreSQL (place=line)."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: 15s safe / 10s otherwise)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Print sample odds lines each iteration",
    )
    args = parser.parse_args()

    api_config = line_config_from_env()
    if args.interval is not None:
        api_config = replace(api_config, poll_interval=args.interval)

    db_config = DatabaseConfig.from_env()
    run_poll(
        api_config=api_config,
        db_config=db_config,
        max_iterations=1 if args.once else None,
        show_samples=args.samples,
    )


if __name__ == "__main__":
    main()
