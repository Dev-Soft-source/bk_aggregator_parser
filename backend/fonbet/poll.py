#!/usr/bin/env python3
"""Poll Fonbet line API every N seconds and import into PostgreSQL."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from config import DatabaseConfig
from db import connect, init_schema, run_migration
from fonbet.sports_reference import resolve_appendix_path
from fonbet.api import FonbetApiError, fetch_list, fetch_list_light, packet_version
from fonbet.config import FonbetApiConfig
from fonbet.importer import import_packet

logger = logging.getLogger(__name__)

DEFAULT_FONBET_SITE = "fonbet.com"
OTHER_BOOKMAKER_SITES = frozenset(
    {"bet365.com", "ligastavok.ru", "betcity.ru", "betcity"}
)


def resolve_site_name(requested: str | None, env_site_name: str | None) -> str:
    """
    Canonical Fonbet site for DB writes.

    - Explicit --site-name wins
    - Env SITE_NAME from another bookmaker is ignored → fonbet.com
    """
    if requested:
        return requested.strip() or DEFAULT_FONBET_SITE
    env_name = (env_site_name or "").strip()
    if not env_name or env_name in OTHER_BOOKMAKER_SITES:
        return DEFAULT_FONBET_SITE
    return env_name


def run_poll(
    *,
    site_name: str,
    db_config: DatabaseConfig,
    api_config: FonbetApiConfig,
    appendix_path: Path,
    init_schema_flag: bool = False,
    migrate_flag: bool = False,
    schema_path: Path = Path("schema.sql"),
    migrate_path: Path = Path("schema_migrate.sql"),
    max_iterations: int | None = None,
    retain_snapshot_years: int | None = None,
    prune_matches_before_year: int | None = None,
) -> None:
    iteration = 0
    version: int | None = None
    retain_years = (
        db_config.retain_snapshot_years
        if retain_snapshot_years is None
        else retain_snapshot_years
    )

    with connect(db_config) as conn:
        if init_schema_flag:
            init_schema(conn, schema_path)
        if migrate_flag:
            run_migration(conn, migrate_path)

        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            try:
                if version is None:
                    packet = fetch_list_light(api_config)
                    source = api_config.list_light_url
                else:
                    packet = fetch_list(version, api_config)
                    source = api_config.list_url(version)

                new_version = packet_version(packet)
                if new_version is None:
                    raise FonbetApiError("Response missing packetVersion")

                snapshot_id, counts = import_packet(
                    conn,
                    packet,
                    source,
                    site_name,
                    appendix_path=appendix_path,
                    retain_snapshot_years=retain_years,
                    prune_matches_before_year=prune_matches_before_year,
                )
                version = new_version

                print(
                    f"[{iteration}] snapshot={snapshot_id} packetVersion={version} "
                    f"sports={counts['sports']} matches={counts['matches']} "
                    f"scores={counts['scores_updated']} odds={counts['odds_lines']} "
                    f"pruned_matches={counts.get('matches_deleted', 0)} "
                    f"pruned_snapshots={counts.get('snapshots_deleted', 0)}"
                )
            except Exception as exc:
                logger.exception("Poll iteration %s failed: %s", iteration, exc)
                print(f"[{iteration}] ERROR: {exc} — resetting with listLight on next tick")
                try:
                    conn.rollback()
                except Exception:
                    logger.exception("Rollback after poll failure failed")
                version = None

            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(api_config.poll_interval)


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Poll Fonbet API and import to PostgreSQL.")
    parser.add_argument("--init-schema", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--site-name", default=None)
    parser.add_argument(
        "--appendix",
        default=None,
        help="Path to Appendix_A_sports_EN.md (default: docs/ or fonbet/)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval seconds (default: POLL_INTERVAL_SECONDS or 5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle only (listLight then list if version known)",
    )
    parser.add_argument(
        "--retain-snapshot-years",
        type=int,
        default=None,
        help="Keep snapshot audit rows for N calendar years (0=disable)",
    )
    parser.add_argument(
        "--prune-matches-before-year",
        type=int,
        default=None,
        help="Delete matches with event_year before this year",
    )
    args = parser.parse_args()

    db_config = DatabaseConfig.from_env()
    api_config = FonbetApiConfig.from_env()
    if args.interval is not None:
        api_config = FonbetApiConfig(
            list_light_url=api_config.list_light_url,
            list_url_base=api_config.list_url_base,
            scope_market=api_config.scope_market,
            lang=api_config.lang,
            poll_interval=args.interval,
            timeout=api_config.timeout,
        )

    site_name = resolve_site_name(args.site_name, db_config.site_name)
    max_iter = 2 if args.once else None  # once = listLight + one list call

    appendix_path = resolve_appendix_path(
        Path(args.appendix) if args.appendix else None
    )
    if appendix_path is None:
        raise SystemExit(
            "Appendix A not found. Place Appendix_A_sports_EN.md under docs/ "
            "or fonbet/, or pass --appendix PATH"
        )

    print(f"Polling every {api_config.poll_interval}s for {site_name}")
    print(f"  listLight: {api_config.list_light_url}")
    print(f"  list:      {api_config.list_url_base}?lang=...&version=<packetVersion>&scopeMarket=...")
    print(f"  appendix:  {appendix_path}")
    if (db_config.site_name or "").strip() in OTHER_BOOKMAKER_SITES and not args.site_name:
        print(
            f"  note: ignored SITE_NAME={db_config.site_name!r} "
            f"(using {site_name} for Fonbet)"
        )

    run_poll(
        site_name=site_name,
        db_config=db_config,
        api_config=api_config,
        appendix_path=appendix_path,
        init_schema_flag=args.init_schema,
        migrate_flag=args.migrate,
        max_iterations=max_iter,
        retain_snapshot_years=args.retain_snapshot_years,
        prune_matches_before_year=args.prune_matches_before_year,
    )


if __name__ == "__main__":
    main()
