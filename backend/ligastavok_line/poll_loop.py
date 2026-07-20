"""Shared Liga Stavok poll loop (used by live and line CLIs)."""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path

from adapters.base import Change, ChangeType
from config import DatabaseConfig
from core.apply_changes import apply_changes
from db import connect
from ligastavok_line.adapter import LigastavokAdapter
from ligastavok_line.api import curl_has_session, save_snapshot
from ligastavok_line.config import (
    LigastavokApiConfig,
    line_prune_absent_from_env,
    line_prune_min_fixtures_from_env,
)
from ligastavok_line.mapper import extract_events

logger = logging.getLogger(__name__)

DEFAULT_LIGASTAVOK_SITE = "ligastavok.ru"
OTHER_BOOKMAKER_SITES = frozenset(
    {
        "fonbet.com",
        "bet365.com",
        "betcity.ru",
        "betcity",
        "1xbet.com",
        "lxbet.com",
    }
)


def resolve_site_name(requested: str | None, env_site_name: str | None) -> str:
    """Canonical Liga Stavok site for DB writes (ignore other bookmakers' SITE_NAME)."""
    if requested:
        return requested.strip() or DEFAULT_LIGASTAVOK_SITE
    env_name = (env_site_name or "").strip()
    if not env_name or env_name in OTHER_BOOKMAKER_SITES:
        return DEFAULT_LIGASTAVOK_SITE
    return env_name


def active_fixture_ids(changes: list[Change]) -> set[int]:
    return {
        int(c.match_payload_id)
        for c in changes
        if c.change_type == ChangeType.FIXTURE and c.match_payload_id is not None
    }


def should_prune_line_absent(
    changes: list[Change],
    *,
    snapshot_ns: str,
    prune_enabled: bool,
    min_fixtures: int = 1,
) -> tuple[bool, set[int]]:
    """
    Prune only on full prematch HTTP snapshots — never on WebSocket deltas.

    WS batches include from_version and only touch a few events; pruning on them
    would delete the rest of the line catalog.
    """
    fixture_ids = active_fixture_ids(changes)
    if not prune_enabled or snapshot_ns != "prematch":
        return False, fixture_ids
    if any(c.from_version is not None for c in changes):
        return False, fixture_ids
    if len(fixture_ids) < min_fixtures:
        return False, fixture_ids
    return True, fixture_ids


def _print_summary(
    iteration: int, summary, changes, counts: dict[str, int] | None = None
) -> None:
    by_type = Counter(c.change_type.value for c in changes)
    extra = ""
    if counts:
        pruned = counts.get("matches_deleted", 0)
        extra = (
            f" db_matches={counts['matches']} db_scores={counts['scores_updated']} "
            f"db_odds={counts['odds_lines']}"
            + (f" pruned={pruned}" if pruned else "")
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
        from ligastavok_line.browser_session import PlaywrightCookieSession

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
                    "If you get 403, ensure Playwright/CDP is on "
                    "(default) or refresh capture.curl cookies.\n"
                    "To disable browser: --no-browser or "
                    "LIGASTAVOK_USE_PLAYWRIGHT=false.\n"
                )

        print(
            f"Polling every {api_config.poll_interval}s "
            f"-> PostgreSQL ({db_config.site_name})"
        )
        place = "line" if api_config.snapshot_ns == "prematch" else "live"
        print(f"  ns: {api_config.snapshot_ns} (place={place})")
        prune_enabled = (
            line_prune_absent_from_env()
            if api_config.snapshot_ns == "prematch"
            else False
        )
        prune_min = line_prune_min_fixtures_from_env()
        if api_config.snapshot_ns == "prematch":
            print(
                f"  prune_absent: {prune_enabled} "
                f"(HTTP snapshots only, min_fixtures={prune_min})"
            )
        if api_config.live_all_sports:
            print(f"  mode: all {api_config.snapshot_ns} sports (paginated)")
        if curl_path is not None:
            print(f"  curl: {curl_path.resolve()}")
        elif api_config.curl_file:
            print(f"  curl: {api_config.curl_file}")
        if output_path is not None:
            print(
                f"  json output: {output_path.resolve()} "
                f"(compact={not api_config.json_pretty})"
            )
        if api_config.snapshot_parallel_pages:
            print(
                f"  http: parallel pages, limit={api_config.snapshot_limit}, "
                f"workers={api_config.snapshot_parallel_workers}"
            )

        iteration = 0
        source_file = (
            "ligastavok line poll"
            if api_config.snapshot_ns == "prematch"
            else "ligastavok live poll"
        )
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
                        f"[{iteration}] wrote {len(events)} events "
                        f"-> {output_path.resolve()}"
                    )

                try:
                    do_prune, active_ids = should_prune_line_absent(
                        changes,
                        snapshot_ns=api_config.snapshot_ns,
                        prune_enabled=prune_enabled,
                        min_fixtures=prune_min,
                    )
                    snapshot_id, counts = apply_changes(
                        conn,
                        changes,
                        site_name=db_config.site_name,
                        packet_version=summary.packet_version,
                        source_file=source_file,
                        retain_snapshot_years=db_config.retain_snapshot_years,
                        prune_absent=do_prune,
                        active_match_ids=active_ids if do_prune else None,
                        prune_place="line" if do_prune else None,
                    )
                except Exception as exc:
                    logger.warning("DB import iteration %s failed: %s", iteration, exc)
                    try:
                        conn.rollback()
                    except Exception:
                        logger.exception("Rollback after import failure failed")
                    _print_summary(iteration, summary, changes, None)
                    continue

                _print_summary(iteration, summary, changes, counts)
                label = (
                    "ws"
                    if any(c.from_version is not None for c in changes)
                    else "http"
                )
                pruned = counts.get("matches_deleted", 0)
                print(
                    f"  imported ({label}) snapshot_id={snapshot_id} "
                    f"matches={counts['matches']} scores={counts['scores_updated']} "
                    f"odds={counts['odds_lines']}"
                    + (f" pruned={pruned}" if pruned else "")
                    + (f" prune_absent={do_prune}" if label == "http" else "")
                )
                if api_config.profile:
                    print(f"  cycle: {(time.perf_counter() - t0) * 1000:.0f}ms")

                if show_samples and iteration == 1:
                    for change_type in ChangeType:
                        sample = next(
                            (c for c in changes if c.change_type == change_type),
                            None,
                        )
                        if sample:
                            print(
                                f"  sample {change_type.value}: "
                                f"match {sample.match_payload_id}"
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
        from ligastavok_line.api import close_http_session

        close_http_session()
