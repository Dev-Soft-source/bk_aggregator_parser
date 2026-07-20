"""Apply normalized adapter changes to PostgreSQL (Fonbet-compatible schema)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import psycopg2.extras

from adapters.base import Change, ChangeType
from fonbet.parsers import event_year_from_start_time, normalize_line_param, unix_to_datetime
from retention import (
    current_utc_year,
    prune_absent_matches,
    prune_orphan_catalog,
    prune_past_place_matches,
    prune_snapshots,
    prune_snapshots_to_current,
    prune_stale_matches,
)

# Frontend queries use ODDS_FACTOR_IDS=921,922,923 — map oversized bookmaker
# factor ids (e.g. Liga Stavok facId) onto the 921/923 2-way slots.
NORMALIZED_FACTOR_IDS: tuple[int, ...] = (921, 922, 923)
_INT32_MAX = 2_147_483_647
_INT32_MIN = -2_147_483_648


def _canonical_factor_id(raw_factor: Any, idx: int) -> int | None:
    """Return an INTEGER-safe factor_id for odds_lines."""
    if raw_factor is not None:
        factor_id = int(raw_factor)
        if _INT32_MIN <= factor_id <= _INT32_MAX:
            return factor_id
    if idx < len(NORMALIZED_FACTOR_IDS):
        return NORMALIZED_FACTOR_IDS[idx]
    return None


def _upsert_site(cur: psycopg2.extensions.cursor, name: str) -> int:
    cur.execute(
        """
        INSERT INTO sites (name)
        VALUES (%s)
        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (name,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _upsert_country(cur: psycopg2.extensions.cursor, name: str) -> int:
    cur.execute(
        """
        INSERT INTO countries (name)
        VALUES (%s)
        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (name,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _group_latest(changes: list[Change]) -> dict[int, dict[str, Any]]:
    """Group changes per match; ODDS is a list (multiple markets per fixture)."""
    by_match: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            ChangeType.FIXTURE: None,
            ChangeType.SCORE: None,
            ChangeType.BETTING_STATUS: None,
            "odds": [],
        }
    )
    for change in changes:
        bucket = by_match[change.match_payload_id]
        if change.change_type == ChangeType.ODDS:
            bucket["odds"].append(change)
        else:
            bucket[change.change_type] = change
    return by_match


def apply_changes(
    conn,
    changes: list[Change],
    *,
    site_name: str,
    packet_version: int,
    source_file: str = "ligastavok",
    retain_snapshot_years: int = 1,
    prune_matches_before_year: int | None = None,
    active_match_ids: set[int] | list[int] | None = None,
    prune_absent: bool = False,
    retain_snapshot_count: int | None = None,
    prune_place: str | None = "live",
    prune_past_hours: int | None = None,
) -> tuple[int, dict[str, int]]:
    """Write adapter changes to PostgreSQL. Returns (snapshot_id, counts)."""
    grouped = _group_latest(changes)
    import_year = current_utc_year()

    counts = {
        "sports": 0,
        "leagues": 0,
        "matches": 0,
        "scores_updated": 0,
        "odds_lines": 0,
        "snapshots_deleted": 0,
        "matches_deleted": 0,
        "leagues_deleted": 0,
        "sports_deleted": 0,
    }

    with conn.cursor() as cur:
        site_id = _upsert_site(cur, site_name)
        cur.execute(
            """
            INSERT INTO import_snapshots (site_id, source_file, packet_version, year)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (site_id, source_file, packet_version, import_year),
        )
        snapshot_id = int(cur.fetchone()[0])

        country_ids: dict[str, int] = {}
        seen_sports: set[int] = set()
        seen_leagues: set[int] = set()
        match_ids: set[int] = set()

        for match_id, type_map in grouped.items():
            fixture = type_map.get(ChangeType.FIXTURE)
            if not fixture:
                continue

            payload = fixture.payload
            sport_id = int(payload["sport_payload_id"])
            league_id = int(payload["league_payload_id"])

            if sport_id not in seen_sports:
                cur.execute(
                    """
                    INSERT INTO sports (site_id, id, name_en, reference_sport_id)
                    VALUES (%s, %s, %s, NULL)
                    ON CONFLICT (site_id, id) DO UPDATE
                    SET name_en = EXCLUDED.name_en
                    """,
                    (site_id, sport_id, payload.get("sport_name") or f"Sport {sport_id}"),
                )
                seen_sports.add(sport_id)
                counts["sports"] += 1

            if league_id not in seen_leagues:
                country_name = payload.get("country_name")
                country_id = None
                if country_name:
                    if country_name not in country_ids:
                        country_ids[country_name] = _upsert_country(cur, str(country_name))
                    country_id = country_ids[country_name]

                cur.execute(
                    """
                    INSERT INTO leagues (site_id, id, sport_id, country_id, name)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (site_id, id) DO UPDATE
                    SET sport_id = EXCLUDED.sport_id,
                        country_id = EXCLUDED.country_id,
                        name = EXCLUDED.name
                    """,
                    (
                        site_id,
                        league_id,
                        sport_id,
                        country_id,
                        payload.get("league_name") or f"League {league_id}",
                    ),
                )
                seen_leagues.add(league_id)
                counts["leagues"] += 1

            start_time = unix_to_datetime(payload.get("start_time_unix"))
            event_year = event_year_from_start_time(start_time, import_year)

            cur.execute(
                """
                INSERT INTO matches (
                    site_id, id, league_id, sport_id, team1, team2,
                    start_time, event_year, place, priority, snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, id) DO UPDATE
                SET league_id = EXCLUDED.league_id,
                    sport_id = EXCLUDED.sport_id,
                    team1 = EXCLUDED.team1,
                    team2 = EXCLUDED.team2,
                    start_time = EXCLUDED.start_time,
                    event_year = EXCLUDED.event_year,
                    place = EXCLUDED.place,
                    priority = EXCLUDED.priority,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (
                    site_id,
                    match_id,
                    league_id,
                    sport_id,
                    payload.get("team1"),
                    payload.get("team2"),
                    start_time,
                    event_year,
                    payload.get("place", "unknown"),
                    payload.get("priority"),
                    snapshot_id,
                ),
            )
            match_ids.add(match_id)
            counts["matches"] += 1

            score_change = type_map.get(ChangeType.SCORE)
            if score_change:
                sp = score_change.payload
                cur.execute(
                    """
                    INSERT INTO match_scores (
                        site_id, match_id, score1, score2, timer_seconds,
                        timer_display, score_function, raw_scores,
                        timer_updated_at, snapshot_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (site_id, match_id) DO UPDATE
                    SET score1 = COALESCE(EXCLUDED.score1, match_scores.score1),
                        score2 = COALESCE(EXCLUDED.score2, match_scores.score2),
                        timer_seconds = COALESCE(
                            EXCLUDED.timer_seconds, match_scores.timer_seconds
                        ),
                        timer_display = COALESCE(
                            EXCLUDED.timer_display, match_scores.timer_display
                        ),
                        score_function = COALESCE(
                            EXCLUDED.score_function, match_scores.score_function
                        ),
                        raw_scores = COALESCE(
                            EXCLUDED.raw_scores, match_scores.raw_scores
                        ),
                        timer_updated_at = CASE
                            -- Running clocks: refresh every poll so the UI ticks
                            -- from the last import, not from a stale TM change.
                            WHEN EXCLUDED.score_function = 'run' THEN NOW()
                            WHEN EXCLUDED.timer_seconds IS DISTINCT FROM match_scores.timer_seconds
                              OR EXCLUDED.timer_display IS DISTINCT FROM match_scores.timer_display
                              OR EXCLUDED.score_function IS DISTINCT FROM match_scores.score_function
                            THEN NOW()
                            ELSE match_scores.timer_updated_at
                        END,
                        snapshot_id = EXCLUDED.snapshot_id
                    """,
                    (
                        site_id,
                        match_id,
                        sp.get("score1"),
                        sp.get("score2"),
                        sp.get("timer_seconds"),
                        sp.get("timer_display"),
                        sp.get("score_function"),
                        psycopg2.extras.Json(sp.get("raw_scores"))
                        if sp.get("raw_scores")
                        else None,
                        snapshot_id,
                    ),
                )
                counts["scores_updated"] += 1

            status_change = type_map.get(ChangeType.BETTING_STATUS)
            if status_change:
                cur.execute(
                    """
                    INSERT INTO betting_status (site_id, match_id, state, snapshot_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (site_id, match_id) DO UPDATE
                    SET state = EXCLUDED.state,
                        snapshot_id = EXCLUDED.snapshot_id
                    """,
                    (
                        site_id,
                        match_id,
                        status_change.payload.get("state", "unknown"),
                        snapshot_id,
                    ),
                )

            odds_changes: list[Change] = type_map.get("odds") or []
            all_factor_ids: list[int] = []
            for odds_change in odds_changes:
                op = odds_change.payload
                outcomes = op.get("outcomes") or []
                market_id = op.get("market_id")
                line_param = normalize_line_param(market_id)
                odds_rows: list[tuple[Any, ...]] = []
                factor_ids_used: list[int] = []
                for idx, outcome in enumerate(outcomes):
                    factor_id = _canonical_factor_id(outcome.get("factor_id"), idx)
                    if factor_id is None:
                        continue
                    factor_ids_used.append(factor_id)
                    all_factor_ids.append(factor_id)
                    line_param_raw = outcome.get("line_param_raw")
                    if line_param_raw is None:
                        raw_factor = outcome.get("factor_id")
                        # Oversized native ids belong in BIGINT line_param_raw.
                        if raw_factor is not None and int(raw_factor) != factor_id:
                            line_param_raw = int(raw_factor)
                    odds_rows.append(
                        (
                            site_id,
                            match_id,
                            op.get("market_event_id") or match_id,
                            op.get("market_event_name") or "main",
                            factor_id,
                            outcome.get("odds"),
                            line_param,
                            line_param_raw,
                            outcome.get("line_param_text"),
                            bool(outcome.get("is_handicap_total")),
                            snapshot_id,
                        )
                    )

                if odds_rows and line_param is not None:
                    cur.execute(
                        """
                        DELETE FROM odds_lines
                        WHERE site_id = %s
                          AND match_id = %s
                          AND line_param = %s
                          AND factor_id <> ALL(%s)
                        """,
                        (site_id, match_id, line_param, factor_ids_used),
                    )
                elif odds_rows:
                    cur.execute(
                        """
                        DELETE FROM odds_lines
                        WHERE site_id = %s
                          AND match_id = %s
                          AND line_param IS NULL
                          AND factor_id <> ALL(%s)
                        """,
                        (site_id, match_id, factor_ids_used),
                    )

                if odds_rows:
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        INSERT INTO odds_lines (
                            site_id, match_id, market_event_id, market_event_name,
                            factor_id, odds, line_param, line_param_raw,
                            line_param_text, is_handicap_total, snapshot_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (site_id, match_id, factor_id, line_param) DO UPDATE
                        SET market_event_id = EXCLUDED.market_event_id,
                            market_event_name = EXCLUDED.market_event_name,
                            odds = EXCLUDED.odds,
                            line_param_raw = EXCLUDED.line_param_raw,
                            line_param_text = EXCLUDED.line_param_text,
                            is_handicap_total = EXCLUDED.is_handicap_total,
                            snapshot_id = EXCLUDED.snapshot_id
                        """,
                        odds_rows,
                        page_size=500,
                    )
                    counts["odds_lines"] += len(odds_rows)

        if retain_snapshot_years > 0:
            before_year = current_utc_year() - retain_snapshot_years + 1
            counts["snapshots_deleted"] = prune_snapshots(cur, site_id, before_year)
        if prune_matches_before_year is not None:
            counts["matches_deleted"] += prune_stale_matches(
                cur, site_id, prune_matches_before_year
            )
        if prune_past_hours is not None and prune_past_hours > 0 and prune_place:
            past_deleted = prune_past_place_matches(
                cur,
                site_id,
                place=prune_place,
                grace_hours=prune_past_hours,
            )
            counts["matches_deleted"] += past_deleted
            if past_deleted:
                orphans = prune_orphan_catalog(cur, site_id)
                counts["leagues_deleted"] += orphans["leagues_deleted"]
                counts["sports_deleted"] += orphans["sports_deleted"]
        if prune_absent:
            keep_ids = set(active_match_ids or ())
            keep_ids.update(match_ids)
            deleted = prune_absent_matches(
                cur, site_id, keep_ids, place=prune_place
            )
            counts["matches_deleted"] += deleted
            if deleted:
                orphans = prune_orphan_catalog(cur, site_id)
                counts["leagues_deleted"] += orphans["leagues_deleted"]
                counts["sports_deleted"] += orphans["sports_deleted"]
            # Replace mode: only the current snapshot is needed.
            counts["snapshots_deleted"] += prune_snapshots_to_current(
                cur, site_id, snapshot_id
            )
        elif retain_snapshot_count is not None and retain_snapshot_count <= 1:
            counts["snapshots_deleted"] += prune_snapshots_to_current(
                cur, site_id, snapshot_id
            )

    conn.commit()
    return snapshot_id, counts
