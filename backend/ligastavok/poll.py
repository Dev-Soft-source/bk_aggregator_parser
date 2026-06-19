#!/usr/bin/env python3
"""Poll Liga Stavok HTTP snapshot and import to PostgreSQL (Fonbet-style)."""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from adapters.base import ChangeType
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect
from ligastavok.adapter import LigastavokAdapter
from ligastavok.api import curl_has_session, save_snapshot
from ligastavok.config import LigastavokApiConfig
from ligastavok.mapper import extract_events

logger = logging.getLogger(__name__)


def _print_summary(iteration: int, summary, changes, counts: dict[str, int] | None = None) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    extra = ""
    if counts:
        extra = (
            f" db_matches={counts['matches']} db_scores={counts['scores_updated']} "
            f"db_odds={counts['odds_lines']}"
        )
    print(
        f"[{iteration}] snapshot ts={summary.packet_version} "
        f"sports={summary.sports} leagues={summary.leagues} "
        f"fixtures={summary.fixtures} scores={summary.score_changes} "
        f"odds_markets={summary.odds_markets} outcomes={summary.odds_outcomes} "
        f"changes={dict(by_type)}{extra}"
    )


def run_poll(
    *,
    api_config: LigastavokApiConfig,
    db_config: DatabaseConfig,
    curl_path: Path | None = None,
    output_path: Path | None = None,
    max_iterations: int | None = None,
    show_samples: bool = False,
) -> None:
    cookie_session = None
    if api_config.use_playwright:
        from ligastavok.browser_session import PlaywrightCookieSession

        cookie_session = PlaywrightCookieSession(api_config)
        cookie_session.start()

    adapter = LigastavokAdapter(api_config, cookie_session=cookie_session)
    try:
        if api_config.use_playwright:
            if api_config.browser_cdp_url:
                print(f"  browser: CDP attach {api_config.browser_cdp_url}")
            print(f"  browser: cookies {adapter.cookie_refresh_schedule()}")
        if curl_path is not None:
            curl_req = adapter.load_curl_file(curl_path)
            if (
                not api_config.use_playwright
                and not curl_has_session(curl_req.headers)
                and not api_config.cookie
            ):
                print(
                    "Warning: capture.curl has no -b cookies. Poll will try anyway. "
                    "If you get 403, use --browser or set LIGASTAVOK_USE_PLAYWRIGHT=true.\n"
                )

        print(f"Polling every {api_config.poll_interval}s -> PostgreSQL ({db_config.site_name})")
        if api_config.live_all_sports:
            print("  mode: all live sports (paginated)")
        if curl_path is not None:
            print(f"  curl: {curl_path.resolve()}")
        elif api_config.curl_file:
            print(f"  curl: {api_config.curl_file}")
        if output_path is not None:
            print(f"  json output: {output_path.resolve()} (compact={not api_config.json_pretty})")
        if api_config.snapshot_parallel_pages:
            print(
                f"  http: parallel pages, limit={api_config.snapshot_limit}, "
                f"workers={api_config.snapshot_parallel_workers}"
            )

        iteration = 0
        with connect(db_config) as conn:
            for packet, changes, summary in adapter.stream_poll_changes(
                max_iterations=max_iterations
            ):
                iteration += 1
                t0 = time.perf_counter() if api_config.profile else 0.0

                if output_path is not None:
                    save_snapshot(packet, output_path, pretty=api_config.json_pretty)
                    events = extract_events(packet)
                    print(
                        f"[{iteration}] wrote {len(events)} events -> {output_path.resolve()}"
                    )

                try:
                    snapshot_id, counts = apply_changes(
                        conn,
                        changes,
                        site_name=db_config.site_name,
                        packet_version=summary.packet_version,
                        source_file="ligastavok poll",
                        retain_snapshot_years=db_config.retain_snapshot_years,
                    )
                except Exception as exc:
                    logger.warning("DB import iteration %s failed: %s", iteration, exc)
                    _print_summary(iteration, summary, changes, None)
                    continue

                _print_summary(iteration, summary, changes, counts)
                label = "ws" if any(c.from_version is not None for c in changes) else "http"
                print(
                    f"  imported ({label}) snapshot_id={snapshot_id} "
                    f"matches={counts['matches']} scores={counts['scores_updated']} "
                    f"odds={counts['odds_lines']}"
                )
                if api_config.profile:
                    print(f"  cycle: {(time.perf_counter() - t0) * 1000:.0f}ms")

                if show_samples and iteration == 1:
                    for change_type in ChangeType:
                        sample = next(
                            (c for c in changes if c.change_type == change_type), None
                        )
                        if sample:
                            print(
                                f"  sample {change_type.value}: match {sample.match_payload_id}"
                            )

                if max_iterations is not None and iteration >= max_iterations:
                    break

        health = adapter.health()
        print(
            f"Health: ok={health.ok} polls={health.poll_count} "
            f"errors={health.error_count} message={health.message}"
        )
    finally:
        adapter.close()
        from ligastavok.api import close_http_session

        close_http_session()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Liga Stavok and import normalized changes to PostgreSQL.",
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
        help="Poll interval seconds (default: LIGASTAVOK_POLL_INTERVAL_SECONDS or 1.5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll cycle only",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="Bookmaker site name in DB (default: SITE_NAME env, e.g. ligastavok.ru)",
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
        help="Refresh Qrator cookies via Playwright (default: LIGASTAVOK_USE_PLAYWRIGHT)",
    )
    args = parser.parse_args()

    db_config = DatabaseConfig.from_env()
    if args.site_name:
        db_config = DatabaseConfig(
            host=db_config.host,
            port=db_config.port,
            name=db_config.name,
            user=db_config.user,
            password=db_config.password,
            site_name=args.site_name,
            retain_snapshot_years=db_config.retain_snapshot_years,
        )

    api_config = LigastavokApiConfig.from_env()
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
