#!/usr/bin/env python3
"""Listen to Bet365 ZAP WebSocket and print incoming frames or parsed odds."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path

from bet365.config import Bet365Config, build_zap_url
from bet365.mapper import print_odds_snapshot, state_summary
from bet365.state import ZapFeedState
from bet365.ws_client import Bet365WsError, listen, listen_browser


def _replay_body(path: Path, *, live_only: bool) -> int:
    body = path.read_text(encoding="utf-8")
    state = ZapFeedState()
    state.apply_body(body)
    summary = state_summary(state)
    print(
        f"Replay {path.name}: {summary.fixtures} soccer fixture(s), "
        f"{summary.odds_markets} with 1X2 odds\n"
    )
    return print_odds_snapshot(state, live_only=live_only)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Listen to Bet365 ZAP data — browser tap (default with --browser) or direct WebSocket.",
    )
    parser.add_argument(
        "--uid",
        help="WebSocket uid query param (direct mode only)",
    )
    parser.add_argument(
        "--url",
        help="Override WS base URL (direct mode)",
    )
    parser.add_argument(
        "--cookie",
        help="Cookie header from bet365.com (direct mode)",
    )
    parser.add_argument(
        "--session-id",
        help="pstk session id (direct mode)",
    )
    parser.add_argument(
        "--nst-token",
        help="Full NST token for direct WebSocket handshake",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="How long to listen (default BET365_LISTEN_SECONDS or 60)",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Stop after N frames",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write frame summaries JSON to this file",
    )
    parser.add_argument(
        "--no-aux",
        action="store_true",
        help="Direct mode: do not open secondary pshudws socket",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Tap frames from CDP Chrome (recommended, like Liga Stavok)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Open Python WebSocket to premws (needs cookie; often 403)",
    )
    parser.add_argument(
        "--odds",
        action="store_true",
        help="Parse soccer Fulltime Result (1X2) instead of raw frame dump",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="With --odds: show in-play matches only (FS=1)",
    )
    parser.add_argument(
        "--body",
        type=Path,
        help="Replay a saved ZAP body file (offline odds test)",
    )
    args = parser.parse_args()

    if args.body:
        if not args.body.is_file():
            print(f"Error: file not found: {args.body}", file=sys.stderr)
            raise SystemExit(1)
        count = _replay_body(args.body, live_only=args.live_only)
        print(f"\nDone. {count} match(es) with 1X2 odds.")
        return

    cfg = Bet365Config.from_env()
    overrides: dict = {}

    if args.seconds is not None:
        overrides["listen_seconds"] = args.seconds
    if args.max_messages is not None:
        overrides["max_messages"] = args.max_messages
    if args.output:
        overrides["output_path"] = str(args.output)
    if args.no_aux:
        overrides["use_aux_socket"] = False

    use_browser = args.browser or (cfg.use_browser and not args.direct)

    if use_browser:
        if overrides:
            cfg = replace(cfg, **overrides)
        print(f"Mode: browser tap (CDP {cfg.browser_cdp_url})")
        print(f"Page: {cfg.browser_url}")
        print(f"Listen: {cfg.listen_seconds}s")
        if args.odds:
            print("Output: parsed soccer 1X2 odds")
        try:
            count = listen_browser(
                cfg,
                duration=cfg.listen_seconds,
                max_messages=cfg.max_messages,
                output=args.output,
                parse_odds=args.odds,
                live_only=args.live_only,
            )
            print(f"\nDone. Received {count} frame(s) from browser.")
        except Bet365WsError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    # Direct Python WebSocket
    if args.uid:
        base = args.url or cfg.ws_url.split("?")[0]
        overrides["ws_url"] = build_zap_url(base, args.uid)
        overrides["ws_uid"] = args.uid
    if args.url and not args.uid:
        overrides["ws_url"] = args.url
    if args.cookie:
        overrides["cookie"] = args.cookie
    if args.session_id:
        overrides["session_id"] = args.session_id
    if args.nst_token:
        overrides["nst_token"] = args.nst_token

    if overrides:
        cfg = replace(cfg, **overrides)

    print(f"Mode: direct WebSocket")
    print(f"URL: {cfg.ws_url}")
    print(f"Aux: {cfg.ws_aux_url if cfg.use_aux_socket else 'disabled'}")
    print(f"Listen: {cfg.listen_seconds}s")
    if not cfg.cookie and not cfg.session_id:
        print(
            "\nWarning: no BET365_COOKIE — likely HTTP 403.\n"
            "Use: python main.py listen bet365 --browser\n"
        )

    try:
        count = asyncio.run(listen(cfg, duration=cfg.listen_seconds, output=args.output))
        print(f"\nDone. Received {count} frame(s).")
    except Bet365WsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
