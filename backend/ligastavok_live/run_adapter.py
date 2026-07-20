#!/usr/bin/env python3
"""Run Liga Stavok adapter: map JSON snapshot or stream WebSocket patches."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from adapters.base import ChangeType
from ligastavok_live.adapter import LigastavokAdapter
from ligastavok_live.api import curl_has_session, parse_curl_file
from ligastavok_live.config import LigastavokApiConfig
from ligastavok_live.ws import LigastavokWsError


def _print_summary(iteration: int, summary, changes) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    print(
        f"[{iteration}] snapshot={summary.is_snapshot} ts={summary.packet_version} "
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

    default_json = Path(__file__).resolve().parent / "ligastavok.json"
    parser = argparse.ArgumentParser(
        description="Liga Stavok adapter — map snapshot JSON or WebSocket updates.",
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default=str(default_json),
        help=f"Snapshot JSON (default: {default_json.name})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="After loading snapshot, subscribe via WebSocket for patch updates",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Poll HTTP snapshot every N seconds (like Fonbet --live)",
    )
    parser.add_argument(
        "--curl",
        type=Path,
        help="cURL file for HTTP poll (default: capture.curl or LIGASTAVOK_CURL_FILE)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: LIGASTAVOK_POLL_INTERVAL_SECONDS or 1.5)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(default_json),
        help=f"With --poll: write snapshot JSON (default: {default_json.name})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --live: process one WS update then exit",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Limit events from snapshot used for WS subscribe (0 = all in file)",
    )
    args = parser.parse_args()

    if args.poll:
        from config import DatabaseConfig
        from dataclasses import replace
        from ligastavok_live.poll import run_poll

        api_config = LigastavokApiConfig.from_env()
        if args.interval is not None:
            api_config = replace(api_config, poll_interval=args.interval)
        curl_path = args.curl
        if curl_path is None and api_config.curl_file:
            curl_path = Path(api_config.curl_file)
        if curl_path is None:
            default_curl = Path(__file__).resolve().parents[1] / "capture.curl"
            if default_curl.is_file():
                curl_path = default_curl
        run_poll(
            api_config=api_config,
            db_config=DatabaseConfig.from_env(),
            curl_path=curl_path,
            output_path=Path(args.output),
            max_iterations=1 if args.once else None,
            show_samples=True,
        )
        return

    path = Path(args.json_file)
    if not path.is_file():
        parser.error(f"File not found: {path}")

    adapter = LigastavokAdapter()
    packet = adapter.load_packet_file(path)

    if args.max_events > 0:
        events = packet.get("result", {}).get("data", [])
        if isinstance(events, list):
            packet = {
                **packet,
                "result": {**packet.get("result", {}), "data": events[: args.max_events]},
            }

    changes, summary = adapter.process_packet(packet)
    print(f"File: {path}")
    _print_summary(1, summary, changes)

    for change_type in ChangeType:
        sample = next((c for c in changes if c.change_type == change_type), None)
        if sample:
            print(f"\nSample {change_type.value} (match {sample.match_payload_id}):")
            print(f"  {json.dumps(sample.payload, ensure_ascii=True)}")

    if not args.live:
        return

    api_config = LigastavokApiConfig.from_env()
    curl_path = Path(api_config.curl_file) if api_config.curl_file else None
    if curl_path is None:
        default_curl = Path(__file__).resolve().parents[1] / "capture.curl"
        curl_path = default_curl if default_curl.is_file() else None

    has_session = bool(api_config.cookie)
    if curl_path and curl_path.is_file():
        curl_req = parse_curl_file(curl_path)
        adapter.load_curl_file(curl_path)
        has_session = has_session or curl_has_session(curl_req.headers)

    if not has_session:
        print(
            "Warning: no session cookies for WebSocket — will try anyway. "
            "If connect fails, add -b cookies to capture.curl or LIGASTAVOK_COOKIE in .env.\n"
        )

    max_iter = 1 if args.once else None
    print(f"\nWebSocket stream (max_messages={max_iter or 'inf'})…")
    iteration = 1
    try:
        stream = adapter.stream_live_changes(max_iterations=max_iter)
    except LigastavokWsError as exc:
        print(f"WebSocket failed: {exc}")
        return

    for _message, live_changes, live_summary in stream:
        iteration += 1
        _print_summary(iteration, live_summary, live_changes)

    health = adapter.health()
    print(f"Health: ok={health.ok} polls={health.poll_count} errors={health.error_count}")


if __name__ == "__main__":
    main()
