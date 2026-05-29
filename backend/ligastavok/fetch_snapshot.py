#!/usr/bin/env python3
"""Download Liga Stavok line snapshot JSON (HTTP)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dataclasses import replace

from ligastavok.api import LigastavokApiError, fetch_snapshot, parse_curl_file, save_snapshot
from ligastavok.config import LigastavokApiConfig
from ligastavok.mapper import extract_events


def main() -> None:
    default_out = Path(__file__).resolve().parent / "ligastavok.json"
    parser = argparse.ArgumentParser(
        description="Fetch Liga Stavok snapshot JSON (requires browser cookies)."
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(default_out),
        help=f"Output file (default: {default_out.name})",
    )
    parser.add_argument(
        "--ns",
        default="live",
        choices=["live", "prematch"],
        help="Line namespace (default: live)",
    )
    parser.add_argument(
        "--game-id",
        type=int,
        default=None,
        help="Sport filter, e.g. 33=football (optional)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Events per page in POST body (default: LIGASTAVOK_SNAPSHOT_LIMIT or 80)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Max pages (default: all when --live-all, else 1)",
    )
    parser.add_argument(
        "--curl",
        type=Path,
        help="Chrome DevTools 'Copy as cURL' file (overrides URL/headers from .env)",
    )
    parser.add_argument(
        "--live-all",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="All live sports, no gameId filter (default: LIGASTAVOK_LIVE_ALL_SPORTS=true)",
    )
    args = parser.parse_args()

    config = LigastavokApiConfig.from_env()
    live_all = config.live_all_sports if args.live_all is None else args.live_all
    max_pages = args.pages
    if max_pages is None:
        max_pages = 0 if live_all else 1
    if live_all != config.live_all_sports or max_pages != config.snapshot_max_pages:
        config = replace(
            config,
            snapshot_limit=args.limit if args.limit is not None else config.snapshot_limit,
            snapshot_max_pages=max_pages,
            live_all_sports=live_all,
        )
    elif args.limit is not None:
        config = replace(config, snapshot_limit=args.limit)
    url: str | None = None
    headers: dict[str, str] | None = None
    method = "GET"
    body: str | None = None

    if args.curl:
        if not args.curl.is_file():
            sys.exit(f"Curl file not found: {args.curl}")
        curl_req = parse_curl_file(args.curl)
        url, headers, method, body = (
            curl_req.url,
            curl_req.headers,
            curl_req.method,
            curl_req.body,
        )
        print(f"Using {method} from curl file: {url}")
        if method == "POST" and not body and not config.snapshot_body:
            print(
                "Warning: curl file has no --data-raw body. Copy Payload from DevTools\n"
                "  into the curl file or set LIGASTAVOK_SNAPSHOT_BODY in .env\n"
            )
        if method == "POST" and args.pages is None and live_all:
            print("Fetching all live sports pages (skip pagination until total reached)")
        elif method == "POST" and args.pages and args.pages > 1:
            print("Note: POST pagination uses skip in JSON body.")
    elif not config.cookie:
        print(
            "Warning: LIGASTAVOK_COOKIE is empty. Fetch will likely fail with 401 (Qrator).\n"
            "See backend/ligastavok/README.md → 'Get JSON from browser'.\n"
        )

    try:
        payload = fetch_snapshot(
            config,
            ns=args.ns,
            game_id=args.game_id,
            limit=args.limit or config.snapshot_limit,
            max_pages=max_pages,
            url=url,
            headers=headers,
            method=method,
            body=body or config.snapshot_body,
            live_all=live_all,
        )
    except LigastavokApiError as exc:
        sys.exit(str(exc))
    except Exception as exc:
        sys.exit(f"Fetch failed: {exc}")

    out = Path(args.output)
    save_snapshot(payload, out)
    events = extract_events(payload)
    total = (payload.get("result") or {}).get("total")
    print(f"Saved {len(events)} events -> {out.resolve()}")
    if total is not None:
        print(f"API total: {total}")


if __name__ == "__main__":
    main()
