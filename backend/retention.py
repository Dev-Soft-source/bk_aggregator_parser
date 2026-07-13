from __future__ import annotations

from datetime import UTC, datetime
from typing import Collection

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


def prune_snapshots_keep_latest(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    keep: int = 20,
) -> int:
    """Keep only the newest `keep` snapshots per site (drop unreferenced older ones)."""
    if keep < 1:
        return 0
    cur.execute(
        """
        DELETE FROM import_snapshots s
        WHERE s.site_id = %s
          AND s.id NOT IN (
              SELECT id FROM import_snapshots
              WHERE site_id = %s
              ORDER BY id DESC
              LIMIT %s
          )
          AND NOT EXISTS (
              SELECT 1 FROM matches m
              WHERE m.site_id = s.site_id AND m.snapshot_id = s.id
          )
        """,
        (site_id, site_id, keep),
    )
    return cur.rowcount


def prune_snapshots_to_current(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    snapshot_id: int,
) -> int:
    """
    Point all live rows at the current snapshot, then delete older snapshots.

    Needed because matches/odds reference import_snapshots with ON DELETE NO ACTION.
    """
    for table in ("matches", "match_scores", "odds_lines", "betting_status"):
        cur.execute(
            f"""
            UPDATE {table}
            SET snapshot_id = %s
            WHERE site_id = %s
              AND snapshot_id IS DISTINCT FROM %s
            """,
            (snapshot_id, site_id, snapshot_id),
        )
    cur.execute(
        """
        DELETE FROM import_snapshots
        WHERE site_id = %s
          AND id <> %s
        """,
        (site_id, snapshot_id),
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


def prune_absent_matches(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    keep_match_ids: Collection[int],
    *,
    place: str | None = "live",
) -> int:
    """
    Delete matches for a site that are not in the current live set.

    Child rows (odds/scores/betting_status) cascade via FK.
    """
    keep = sorted({int(x) for x in keep_match_ids})
    if not keep:
        # Refuse empty keep-set — would wipe the whole site on a bad poll.
        return 0
    if place:
        cur.execute(
            """
            DELETE FROM matches
            WHERE site_id = %s
              AND place = %s
              AND id <> ALL(%s)
            """,
            (site_id, place, keep),
        )
    else:
        cur.execute(
            """
            DELETE FROM matches
            WHERE site_id = %s
              AND id <> ALL(%s)
            """,
            (site_id, keep),
        )
    return cur.rowcount


def prune_past_place_matches(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    *,
    place: str = "line",
    grace_hours: int = 48,
) -> int:
    """Delete place matches whose kickoff is older than now - grace_hours."""
    if grace_hours < 0:
        return 0
    cur.execute(
        """
        DELETE FROM matches
        WHERE site_id = %s
          AND place = %s
          AND start_time IS NOT NULL
          AND start_time < (NOW() AT TIME ZONE 'utc') - (%s * INTERVAL '1 hour')
        """,
        (site_id, place, int(grace_hours)),
    )
    return cur.rowcount


def prune_orphan_catalog(
    cur: psycopg2.extensions.cursor,
    site_id: int,
) -> dict[str, int]:
    """Remove leagues/sports with no remaining matches for the site."""
    cur.execute(
        """
        DELETE FROM leagues l
        WHERE l.site_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM matches m
              WHERE m.site_id = l.site_id AND m.league_id = l.id
          )
        """,
        (site_id,),
    )
    leagues = cur.rowcount
    cur.execute(
        """
        DELETE FROM sports s
        WHERE s.site_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM matches m
              WHERE m.site_id = s.site_id AND m.sport_id = s.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM leagues l
              WHERE l.site_id = s.site_id AND l.sport_id = s.id
          )
        """,
        (site_id,),
    )
    return {"leagues_deleted": leagues, "sports_deleted": cur.rowcount}
