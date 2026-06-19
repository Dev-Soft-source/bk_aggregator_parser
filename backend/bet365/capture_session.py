#!/usr/bin/env python3
"""Capture Bet365 uid + cookies from CDP Chrome (no DevTools copy-paste)."""

from __future__ import annotations

import argparse
import logging
import sys

from bet365.browser_session import Bet365BrowserError, capture_from_browser
from bet365.config import Bet365Config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Capture Bet365 ZAP uid and pstk cookie from Chrome CDP (like Liga Stavok browser refresh).",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=None,
        help="Seconds to wait for WebSocket uid (default BET365_BROWSER_TIMEOUT_SECONDS)",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Print lines ready to paste into backend/.env",
    )
    args = parser.parse_args()

    cfg = Bet365Config.from_env()
    try:
        captured = capture_from_browser(cfg)
    except Bet365BrowserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.env:
        print(f"BET365_WS_UID={captured.uid}")
        print(f"BET365_COOKIE={captured.cookie}")
        print(f"BET365_SESSION_ID={captured.session_id}")
        if captured.premws_url:
            print(f"# premws: {captured.premws_url}")
        if captured.aux_url:
            print(f"# aux: {captured.aux_url}")
    else:
        print(f"uid:         {captured.uid}")
        print(f"session_id:  {captured.session_id}")
        print(f"premws:      {captured.premws_url}")
        print(f"aux:         {captured.aux_url}")
        print(f"cookie:      {captured.cookie[:80]}… ({len(captured.cookie)} chars)")
        print(f"ws_urls:     {len(captured.ws_urls)} seen")
        for url in captured.ws_urls:
            print(f"  {url}")

    print("\nThen listen:")
    print(f"  python main.py listen bet365 --uid {captured.uid} --cookie \"<paste cookie>\"")


if __name__ == "__main__":
    main()
