#!/usr/bin/env python3
"""Phase 0: init schema, import sample packet, verify booker_adapter."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import psycopg2
from psycopg2 import sql

from config import DatabaseConfig
from db import connect, init_schema, run_migration
from fonbet.importer import import_packet, load_packet
from fonbet.odds_config import allowed_factor_ids


def ensure_database(config: DatabaseConfig) -> None:
    """Create booker_adapter if it does not exist (connects to postgres DB)."""
    admin_dsn = (
        f"host={config.host} port={config.port} dbname=postgres "
        f"user={config.user} password={config.password}"
    )
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (config.name,),
            )
            if cur.fetchone():
                print(f"Database {config.name!r} already exists.")
                return
            print(f"Creating database {config.name!r} …")
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.name))
            )
    finally:
        conn.close()


def verify(conn) -> list[str]:
    errors: list[str] = []
    config = DatabaseConfig.from_env()
    factors = sorted(allowed_factor_ids())

    with conn.cursor() as cur:
        if config.name != "booker_adapter":
            errors.append(
                f"DATABASE_URL dbname is {config.name!r}, expected 'booker_adapter'"
            )

        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        table_count = cur.fetchone()[0]
        if table_count < 8:
            errors.append(f"Expected at least 8 tables, found {table_count}")

        cur.execute("SELECT name FROM sites")
        sites = [row[0] for row in cur.fetchall()]
        if config.site_name not in sites:
            errors.append(f"Site {config.site_name!r} not in sites table")

        cur.execute(
            """
            SELECT match_id, COUNT(*) AS n
            FROM odds_lines
            GROUP BY site_id, match_id
            HAVING COUNT(*) > 2
            """
        )
        over = cur.fetchall()
        if over:
            errors.append(
                f"Matches with >2 odds rows: {len(over)} (e.g. match_id={over[0][0]} n={over[0][1]})"
            )

        cur.execute(
            """
            SELECT DISTINCT factor_id FROM odds_lines ORDER BY factor_id
            """
        )
        db_factors = [row[0] for row in cur.fetchall()]
        extra = set(db_factors) - set(factors)
        if extra:
            errors.append(f"Unexpected factor_ids in DB: {sorted(extra)}")
        missing = set(factors) - set(db_factors)
        if missing and not db_factors:
            errors.append(
                f"No odds yet for configured factors {factors} (import may have no matching lines)"
            )

        cur.execute("SELECT COUNT(*) FROM matches")
        match_count = cur.fetchone()[0]
        if match_count == 0:
            errors.append("No matches in database after import")

    return errors


def main() -> int:
    config = DatabaseConfig.from_env()
    test_json = BACKEND / "fonbet" / "test.json"
    schema = BACKEND / "schema.sql"
    migrate = BACKEND / "schema_migrate.sql"

    print(f"Database: {config.name} @ {config.host}:{config.port}")
    print(f"Allowed factor IDs: {sorted(allowed_factor_ids())}")

    if not test_json.is_file():
        print(f"ERROR: missing {test_json}")
        return 1

    try:
        ensure_database(config)
        with connect(config) as conn:
            print("Applying schema.sql …")
            init_schema(conn, schema)
            if migrate.is_file():
                run_migration(conn, migrate)

            packet = load_packet(test_json)
            print(f"Importing {test_json.name} …")
            snapshot_id, counts = import_packet(
                conn,
                packet,
                str(test_json),
                config.site_name,
                appendix_path=BACKEND / "fonbet" / "Appendix_A_sports_EN.md",
            )
            print(
                f"  snapshot={snapshot_id} matches={counts['matches']} "
                f"odds={counts['odds_lines']} sports={counts['sports']}"
            )

            print("Verifying Phase 0 …")
            errors = verify(conn)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    if errors:
        for err in errors:
            print(f"  FAIL: {err}")
        return 1

    print("Phase 0 setup OK.")
    print("Next: python main.py poll   |   cd frontend && npm run dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
