"""Cleanup mislabeled Betcity site rows (e.g. truncated `betcity.`)."""

from __future__ import annotations

import logging

import psycopg2.extensions

from betcity_live.config import DEFAULT_SITE_NAME, SITE_NAME_ALIASES

logger = logging.getLogger(__name__)


def cleanup_alias_sites(
    conn: psycopg2.extensions.connection,
    *,
    canonical: str = DEFAULT_SITE_NAME,
) -> dict[str, int]:
    """
    Copy data from truncated/alias site names into the canonical Betcity site,
    then delete the alias. Safe for repeated runs.

    Uses INSERT…ON CONFLICT for tables keyed by (site_id, …). Snapshots are
    reassigned with UPDATE because their PK is global `id`.
    """
    counts = {
        "aliases_found": 0,
        "sports_copied": 0,
        "leagues_copied": 0,
        "matches_copied": 0,
        "scores_copied": 0,
        "odds_copied": 0,
        "status_copied": 0,
        "snapshots_moved": 0,
        "sites_deleted": 0,
    }
    aliases = [
        alias
        for alias, target in SITE_NAME_ALIASES.items()
        if target == canonical and alias != canonical
    ]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name FROM sites
            WHERE name = ANY(%s)
               OR (name LIKE 'betcity.%%' AND name <> %s)
            ORDER BY id
            """,
            (aliases, canonical),
        )
        alias_rows = [(int(r[0]), str(r[1])) for r in cur.fetchall()]
        counts["aliases_found"] = len(alias_rows)
        if not alias_rows:
            return counts

        cur.execute(
            """
            INSERT INTO sites (name)
            VALUES (%s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (canonical,),
        )
        canonical_id = int(cur.fetchone()[0])

        for alias_id, alias_name in alias_rows:
            logger.warning(
                "Migrating Betcity alias site %r (id=%s) -> %r (id=%s)",
                alias_name,
                alias_id,
                canonical,
                canonical_id,
            )

            cur.execute(
                """
                INSERT INTO sports (site_id, id, name_en, reference_sport_id, alias, sort_order, tab_caption)
                SELECT %s, id, name_en, reference_sport_id, alias, sort_order, tab_caption
                FROM sports
                WHERE site_id = %s
                ON CONFLICT (site_id, id) DO UPDATE
                SET name_en = EXCLUDED.name_en
                """,
                (canonical_id, alias_id),
            )
            counts["sports_copied"] += cur.rowcount

            cur.execute(
                """
                INSERT INTO leagues (site_id, id, sport_id, country_id, name, region_id, geo_category_id)
                SELECT %s, id, sport_id, country_id, name, region_id, geo_category_id
                FROM leagues
                WHERE site_id = %s
                ON CONFLICT (site_id, id) DO UPDATE
                SET sport_id = EXCLUDED.sport_id,
                    country_id = EXCLUDED.country_id,
                    name = EXCLUDED.name
                """,
                (canonical_id, alias_id),
            )
            counts["leagues_copied"] += cur.rowcount

            # Snapshot PK is global id — reassign site only.
            cur.execute(
                """
                UPDATE import_snapshots
                SET site_id = %s
                WHERE site_id = %s
                """,
                (canonical_id, alias_id),
            )
            counts["snapshots_moved"] += cur.rowcount

            cur.execute(
                """
                INSERT INTO matches (
                    site_id, id, league_id, sport_id, team1, team2,
                    team1_id, team2_id, start_time, event_year, place,
                    event_num, priority, snapshot_id
                )
                SELECT
                    %s, id, league_id, sport_id, team1, team2,
                    team1_id, team2_id, start_time, event_year, place,
                    event_num, priority, snapshot_id
                FROM matches
                WHERE site_id = %s
                ON CONFLICT (site_id, id) DO UPDATE
                SET league_id = EXCLUDED.league_id,
                    sport_id = EXCLUDED.sport_id,
                    team1 = EXCLUDED.team1,
                    team2 = EXCLUDED.team2,
                    team1_id = EXCLUDED.team1_id,
                    team2_id = EXCLUDED.team2_id,
                    start_time = EXCLUDED.start_time,
                    event_year = EXCLUDED.event_year,
                    place = EXCLUDED.place,
                    event_num = EXCLUDED.event_num,
                    priority = EXCLUDED.priority,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (canonical_id, alias_id),
            )
            counts["matches_copied"] += cur.rowcount

            cur.execute(
                """
                INSERT INTO match_scores (
                    site_id, match_id, score1, score2, timer_seconds,
                    timer_display, timer_direction, live_delay, score_function,
                    raw_scores, subscores, timer_updated_at, snapshot_id
                )
                SELECT
                    %s, match_id, score1, score2, timer_seconds,
                    timer_display, timer_direction, live_delay, score_function,
                    raw_scores, subscores, timer_updated_at, snapshot_id
                FROM match_scores
                WHERE site_id = %s
                ON CONFLICT (site_id, match_id) DO UPDATE
                SET score1 = EXCLUDED.score1,
                    score2 = EXCLUDED.score2,
                    timer_seconds = EXCLUDED.timer_seconds,
                    timer_display = EXCLUDED.timer_display,
                    timer_direction = EXCLUDED.timer_direction,
                    live_delay = EXCLUDED.live_delay,
                    score_function = EXCLUDED.score_function,
                    raw_scores = EXCLUDED.raw_scores,
                    subscores = EXCLUDED.subscores,
                    timer_updated_at = EXCLUDED.timer_updated_at,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (canonical_id, alias_id),
            )
            counts["scores_copied"] += cur.rowcount

            cur.execute(
                """
                INSERT INTO odds_lines (
                    site_id, match_id, market_event_id, market_event_name,
                    factor_id, odds, line_param, line_param_raw,
                    line_param_text, is_handicap_total, snapshot_id
                )
                SELECT
                    %s, match_id, market_event_id, market_event_name,
                    factor_id, odds, line_param, line_param_raw,
                    line_param_text, is_handicap_total, snapshot_id
                FROM odds_lines
                WHERE site_id = %s
                ON CONFLICT (site_id, match_id, factor_id, line_param) DO UPDATE
                SET market_event_id = EXCLUDED.market_event_id,
                    market_event_name = EXCLUDED.market_event_name,
                    odds = EXCLUDED.odds,
                    line_param_raw = EXCLUDED.line_param_raw,
                    line_param_text = EXCLUDED.line_param_text,
                    is_handicap_total = EXCLUDED.is_handicap_total,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (canonical_id, alias_id),
            )
            counts["odds_copied"] += cur.rowcount

            cur.execute(
                """
                INSERT INTO betting_status (
                    site_id, match_id, state, partial_factor_ids, snapshot_id
                )
                SELECT %s, match_id, state, partial_factor_ids, snapshot_id
                FROM betting_status
                WHERE site_id = %s
                ON CONFLICT (site_id, match_id) DO UPDATE
                SET state = EXCLUDED.state,
                    partial_factor_ids = EXCLUDED.partial_factor_ids,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (canonical_id, alias_id),
            )
            counts["status_copied"] += cur.rowcount

            cur.execute("DELETE FROM odds_lines WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM match_scores WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM betting_status WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM matches WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM leagues WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM sports WHERE site_id = %s", (alias_id,))
            cur.execute("DELETE FROM sites WHERE id = %s", (alias_id,))
            counts["sites_deleted"] += cur.rowcount

    conn.commit()
    logger.info("Betcity alias cleanup done: %s", counts)
    return counts
