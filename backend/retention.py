from __future__ import annotations

from datetime import UTC, datetime

import psycopg2.extensions


def current_utc_year() -> int:
    return datetime.now(tz=UTC).year


def prune_snapshots(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    before_year: int,
) -> int:
    """Delete import_snapshots older than before_year not linked to current matches."""
    cur.execute(
        """
        DELETE FROM import_snapshots s
        WHERE s.site_id = %s
          AND s.year < %s
          AND NOT EXISTS (
              SELECT 1 FROM matches m
              WHERE m.site_id = s.site_id AND m.snapshot_id = s.id
          )
        """,
        (site_id, before_year),
    )
    return cur.rowcount


def prune_stale_matches(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    before_year: int,
) -> int:
    """Remove matches (and dependent rows) whose event year is before before_year."""
    cur.execute(
        """
        DELETE FROM matches
        WHERE site_id = %s
          AND event_year IS NOT NULL
          AND event_year < %s
        """,
        (site_id, before_year),
    )
    return cur.rowcount
