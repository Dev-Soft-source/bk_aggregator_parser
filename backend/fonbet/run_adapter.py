#!/usr/bin/env python3
"""Run Fonbet adapter: map JSON file or stream live API changes."""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

from adapters.base import ChangeType
from fonbet.adapter import FonbetAdapter


def _print_summary(iteration: int, summary, changes) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    snap = "snapshot" if summary.is_snapshot else "delta"
    print(
        f"[{iteration}] {snap} packetVersion={summary.packet_version} "
        f"fromVersion={summary.from_version} "
        f"sports={summary.sports} leagues={summary.leagues} "
        f"fixtures={summary.fixtures} scores={summary.score_changes} "
        f"status={summary.betting_status_changes} "
        f"odds_markets={summary.odds_markets} outcomes={summary.odds_outcomes} "
        f"changes={dict(by_type)}"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Fonbet adapter — map packet or poll live.")
    parser.add_argument(
        "json_file",
        nargs="?",
        help="Path to Fonbet JSON (default: test.json when not using --live)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Poll Fonbet API (listLight then list?version=)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --live: single iteration (or listLight + one list)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (overrides POLL_INTERVAL_SECONDS)",
    )
    args = parser.parse_args()

    adapter = FonbetAdapter()
    if args.interval is not None:
        from fonbet.config import FonbetApiConfig

        cfg = adapter._api  # noqa: SLF001
        adapter = FonbetAdapter(
            FonbetApiConfig(
                list_light_url=cfg.list_light_url,
                list_url_base=cfg.list_url_base,
                scope_market=cfg.scope_market,
                lang=cfg.lang,
                poll_interval=args.interval,
                timeout=cfg.timeout,
                snapshot_every=cfg.snapshot_every,
                line_past_grace_hours=cfg.line_past_grace_hours,
            )
        )

    if args.live:
        max_iter = 2 if args.once else None
        print(f"Streaming live changes (max_iterations={max_iter or '∞'})…")
        iteration = 0
        for _packet, changes, summary in adapter.stream_live_changes_resilient(
            max_iterations=max_iter
        ):
            iteration += 1
            _print_summary(iteration, summary, changes)
        health = adapter.health()
        print(f"Health: ok={health.ok} polls={health.poll_count} errors={health.error_count}")
        return

    path = Path(args.json_file or Path(__file__).resolve().parent / "test.json")
    if not path.is_file():
        parser.error(f"File not found: {path}")

    packet = adapter.load_packet_file(path)
    changes = adapter.map_packet_to_changes(packet)
    summary = adapter.packet_summary(packet)

    print(f"File: {path}")
    _print_summary(1, summary, changes)

    if args.once:
        return

    # Show sample changes per type
    for change_type in ChangeType:
        sample = next((c for c in changes if c.change_type == change_type), None)
        if sample:
            print(f"\nSample {change_type.value} (match {sample.match_payload_id}):")
            print(f"  {sample.payload}")


if __name__ == "__main__":
    main()
