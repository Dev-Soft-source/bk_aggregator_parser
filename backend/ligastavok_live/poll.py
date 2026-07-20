#!/usr/bin/env python3
"""Poll Liga Stavok live and import to PostgreSQL."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from config import DatabaseConfig
from ligastavok_live.poll_loop import resolve_site_name, run_poll
from ligastavok_live.config import DEFAULT_SITE_NAME, live_config_from_env

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Liga Stavok live and import normalized changes to PostgreSQL.",
    )
    parser.add_argument(
        "--curl",
        type=Path,
        help="Chrome DevTools cURL file (default: LIGASTAVOK_CURL_FILE or capture.curl)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: LIGASTAVOK_POLL_INTERVAL_SECONDS)",
    )
    parser.add_argument("--once", action="store_true", help="Run one poll cycle only")
    parser.add_argument(
        "--site-name",
        default=None,
        help=f"Bookmaker site name in DB (default: {DEFAULT_SITE_NAME})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Optional: also write raw API JSON each poll",
    )
    parser.add_argument(
        "--live-all",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="All live sports (default: LIGASTAVOK_LIVE_ALL_SPORTS=true)",
    )
    parser.add_argument(
        "--browser",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Refresh Qrator cookies via Playwright/CDP "
            "(default: on; use --no-browser to disable)"
        ),
    )
    args = parser.parse_args()

    db_config = DatabaseConfig.from_env()
    site_name = resolve_site_name(args.site_name, db_config.site_name)
    if site_name != db_config.site_name:
        db_config = replace(db_config, site_name=site_name)

    api_config = live_config_from_env()
    overrides: dict = {}
    if args.interval is not None:
        overrides["poll_interval"] = args.interval
    if args.live_all is not None:
        overrides["live_all_sports"] = args.live_all
    if args.browser is not None:
        overrides["use_playwright"] = args.browser
    if overrides:
        api_config = replace(api_config, **overrides)

    curl_path = args.curl
    if curl_path is None and api_config.curl_file:
        curl_path = Path(api_config.curl_file)
    if curl_path is None:
        default_curl = Path(__file__).resolve().parents[1] / "capture.curl"
        if default_curl.is_file():
            curl_path = default_curl

    run_poll(
        api_config=api_config,
        db_config=db_config,
        curl_path=curl_path,
        output_path=Path(args.output) if args.output else None,
        max_iterations=1 if args.once else None,
    )


if __name__ == "__main__":
    main()
