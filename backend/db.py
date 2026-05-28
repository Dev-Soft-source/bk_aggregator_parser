from __future__ import annotations

from pathlib import Path

import psycopg2
from psycopg2.extensions import connection as Connection

from config import DatabaseConfig


def connect(config: DatabaseConfig | None = None) -> Connection:
    cfg = config or DatabaseConfig.from_env()
    return psycopg2.connect(cfg.dsn)


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    for part in sql.split(";"):
        block = part.strip()
        if not block:
            continue
        lines = [
            line
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if lines:
            statements.append(block)
    return statements


def _run_sql_file(conn: Connection, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql)
    if not statements:
        return
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def init_schema(conn: Connection, schema_path: Path) -> None:
    _run_sql_file(conn, schema_path)


def run_migration(conn: Connection, migration_path: Path) -> None:
    if not migration_path.is_file():
        return
    _run_sql_file(conn, migration_path)
