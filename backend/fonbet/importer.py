#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg2.extras

from config import DatabaseConfig
from db import connect, init_schema, run_migration
from fonbet.api import is_snapshot_packet
from fonbet.sports_reference import (
    load_appendix_sports_en,
    resolve_appendix_path,
    resolve_name_en,
)
from fonbet.parsers import (
    build_sport_prefixes,
    build_sports_maps,
    event_year_from_start_time,
    find_root_match_id,
    is_handicap_or_total,
    millis_to_datetime,
    normalize_line_param,
    parse_country_and_league,
    resolve_match_id_for_update,
    resolve_root_sport_id,
    unix_to_datetime,
)
from fonbet.odds_config import allowed_factor_ids, factor_is_allowed
from fonbet.lifecycle import (
    active_live_match_ids,
    collect_soft_finished_match_ids,
    normalize_fonbet_betting_state,
    should_keep_last_odds,
    should_persist_fixture,
)
from retention import (
    current_utc_year,
    delete_matches_by_ids,
    prune_absent_matches,
    prune_orphan_catalog,
    prune_past_place_matches,
    prune_snapshots,
    prune_snapshots_to_current,
    prune_stale_matches,
)


def load_packet(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def upsert_site(cur: psycopg2.extensions.cursor, name: str) -> int:
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
    return row[0]


def seed_sport_reference(
    cur: psycopg2.extensions.cursor,
    appendix_path: Path | None = None,
) -> int:
    resolved = resolve_appendix_path(appendix_path)
    if resolved is None:
        return 0
    appendix = load_appendix_sports_en(resolved)
    if not appendix:
        return 0

    rows = [(sport_id, f"sr:sport:{sport_id}", name_en) for sport_id, name_en in appendix.items()]
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO sport_reference (sport_id, urn, name_en)
        VALUES (%s, %s, %s)
        ON CONFLICT (sport_id) DO UPDATE
        SET urn = EXCLUDED.urn,
            name_en = EXCLUDED.name_en
        """,
        rows,
        page_size=500,
    )
    return len(rows)


def upsert_country(cur: psycopg2.extensions.cursor, name: str) -> int:
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
    return row[0]


def apply_retention(
    cur: psycopg2.extensions.cursor,
    site_id: int,
    retain_snapshot_years: int,
    prune_matches_before_year: int | None = None,
) -> dict[str, int]:
    if retain_snapshot_years <= 0 and prune_matches_before_year is None:
        return {"snapshots_deleted": 0, "matches_deleted": 0}

    snapshots_deleted = 0
    matches_deleted = 0

    if retain_snapshot_years > 0:
        snapshot_before_year = current_utc_year() - retain_snapshot_years + 1
        snapshots_deleted = prune_snapshots(cur, site_id, snapshot_before_year)

    if prune_matches_before_year is not None:
        matches_deleted = prune_stale_matches(cur, site_id, prune_matches_before_year)

    return {
        "snapshots_deleted": snapshots_deleted,
        "matches_deleted": matches_deleted,
    }


def _load_known_match_ids(cur: psycopg2.extensions.cursor, site_id: int) -> set[int]:
    cur.execute("SELECT id FROM matches WHERE site_id = %s", (site_id,))
    return {int(row[0]) for row in cur.fetchall()}


def _merge_live_payload(
    match_id: int,
    event_miscs: dict[int, dict[str, Any]],
    live_infos: dict[int, dict[str, Any]],
    events_by_id: dict[int, dict[str, Any]],
    known_match_ids: set[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    misc: dict[str, Any] = {}
    live: dict[str, Any] = {}

    for source in (event_miscs, live_infos):
        for eid, payload in source.items():
            if resolve_match_id_for_update(eid, events_by_id, known_match_ids) == match_id:
                if source is event_miscs:
                    misc = {**misc, **payload}
                else:
                    live = {**live, **payload}

    return misc, live


def _collect_score_update_ids(
    match_ids: set[int],
    event_miscs: dict[int, dict[str, Any]],
    live_infos: dict[int, dict[str, Any]],
    event_blocks: dict[int, dict[str, Any]],
    events_by_id: dict[int, dict[str, Any]],
    known_match_ids: set[int],
) -> set[int]:
    update_ids = set(match_ids)
    candidate_ids = set(event_miscs) | set(live_infos) | set(event_blocks)
    for event_id in candidate_ids:
        root_id = resolve_match_id_for_update(event_id, events_by_id, known_match_ids)
        if root_id is not None:
            update_ids.add(root_id)
    return update_ids


def import_packet(
    conn,
    packet: dict[str, Any],
    source_file: str,
    site_name: str,
    appendix_path: Path | None = None,
    retain_snapshot_years: int = 1,
    prune_matches_before_year: int | None = None,
    *,
    keep_current_only: bool = True,
    line_past_grace_hours: int | None = None,
) -> tuple[int, dict[str, int]]:
    sports = packet.get("sports", [])
    events = packet.get("events", [])
    event_miscs = {item["id"]: item for item in packet.get("eventMiscs", [])}
    event_blocks = {item["eventId"]: item for item in packet.get("eventBlocks", [])}
    live_infos = {item["eventId"]: item for item in packet.get("liveEventInfos", [])}
    custom_factors = packet.get("customFactors", [])
    events_by_id = {event["id"]: event for event in events}

    if line_past_grace_hours is None:
        from fonbet.config import FonbetApiConfig

        line_past_grace_hours = FonbetApiConfig.from_env().line_past_grace_hours

    with conn.cursor() as cur:
        site_id = upsert_site(cur, site_name)

        import_year = current_utc_year()
        cur.execute(
            """
            INSERT INTO import_snapshots (site_id, source_file, packet_version, year)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (site_id, source_file, packet.get("packetVersion"), import_year),
        )
        snapshot_id = cur.fetchone()[0]

        resolved_appendix = resolve_appendix_path(appendix_path)
        reference_count = seed_sport_reference(cur, resolved_appendix)
        appendix_names = load_appendix_sports_en(resolved_appendix)
        if reference_count == 0:
            raise RuntimeError(
                "sport_reference seed is empty — Appendix A not found. "
                "Expected docs/Appendix_A_sports_EN.md or fonbet/Appendix_A_sports_EN.md "
                "(or pass --appendix)."
            )

        country_ids: dict[str, int] = {}
        sports_by_id, league_to_sport = build_sports_maps(sports)
        sport_prefixes = build_sport_prefixes(sports)
        sports_inserted = 0

        for sport in sports:
            if sport.get("kind") != "sport":
                continue
            ref_id, name_en = resolve_name_en(
                sport["id"],
                appendix_names,
                sport.get("name"),
                sport.get("alias"),
            )
            if not name_en:
                name_en = sport.get("name") or sport.get("alias") or f"Sport {sport['id']}"

            cur.execute(
                """
                INSERT INTO sports (
                    site_id, id, name_en, reference_sport_id,
                    alias, sort_order, tab_caption
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, id) DO UPDATE
                SET name_en = EXCLUDED.name_en,
                    reference_sport_id = EXCLUDED.reference_sport_id,
                    alias = EXCLUDED.alias,
                    sort_order = EXCLUDED.sort_order,
                    tab_caption = EXCLUDED.tab_caption
                """,
                (
                    site_id,
                    sport["id"],
                    name_en,
                    ref_id,
                    sport.get("alias"),
                    sport.get("sortOrder"),
                    sport.get("tabCaption"),
                ),
            )
            sports_inserted += 1

        leagues_inserted = 0
        for segment in sports:
            if segment.get("kind") != "segment":
                continue

            root_sport_id = resolve_root_sport_id(segment["id"], sports_by_id)
            root_sport = sports_by_id.get(root_sport_id or 0, {})
            country_name, _ = parse_country_and_league(
                segment["name"],
                sport_prefixes=sport_prefixes,
                root_sport_name=root_sport.get("name"),
            )
            country_id = None
            if country_name:
                if country_name not in country_ids:
                    country_ids[country_name] = upsert_country(cur, country_name)
                country_id = country_ids[country_name]

            parent_sport_id = root_sport_id
            if parent_sport_id is None:
                continue

            cur.execute(
                """
                INSERT INTO leagues (
                    site_id, id, sport_id, country_id, name, region_id, geo_category_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, id) DO UPDATE
                SET sport_id = EXCLUDED.sport_id,
                    country_id = EXCLUDED.country_id,
                    name = EXCLUDED.name,
                    region_id = EXCLUDED.region_id,
                    geo_category_id = EXCLUDED.geo_category_id
                """,
                (
                    site_id,
                    segment["id"],
                    parent_sport_id,
                    country_id,
                    segment["name"],
                    segment.get("regionId"),
                    segment.get("geoCategoryId"),
                ),
            )
            leagues_inserted += 1

        level_one_events = [event for event in events if event.get("level") == 1]
        known_match_ids = _load_known_match_ids(cur, site_id)
        soft_finished_ids = collect_soft_finished_match_ids(
            events=events,
            events_by_id=events_by_id,
            event_miscs=event_miscs,
            live_infos=live_infos,
            event_blocks=event_blocks,
            custom_factors=custom_factors,
            sports_by_id=sports_by_id,
            league_to_sport=league_to_sport,
            known_match_ids=known_match_ids,
            resolve_match_id=resolve_match_id_for_update,
        )
        match_ids: set[int] = set()
        matches_inserted = 0

        for event in level_one_events:
            place = event.get("place", "unknown")
            # Live snapshot poll: only persist active live rows. Finished /
            # notActive omitted so prune_absent(place=live) removes prior live.
            if not should_persist_fixture(place, mode="live") and not should_persist_fixture(
                place, mode="line"
            ):
                continue
            if int(event["id"]) in soft_finished_ids:
                continue

            league_id = event.get("sportId")
            sport_id = league_to_sport.get(league_id) if league_id else None
            if sport_id is None:
                continue

            start_time = unix_to_datetime(event.get("startTime"))
            event_year = event_year_from_start_time(start_time, import_year)

            cur.execute(
                """
                INSERT INTO matches (
                    site_id, id, league_id, sport_id, team1, team2, team1_id, team2_id,
                    start_time, event_year, place, event_num, priority, snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                (
                    site_id,
                    event["id"],
                    league_id,
                    sport_id,
                    event.get("team1"),
                    event.get("team2"),
                    event.get("team1Id"),
                    event.get("team2Id"),
                    start_time,
                    event_year,
                    place,
                    event.get("num"),
                    event.get("priority"),
                    snapshot_id,
                ),
            )
            match_ids.add(event["id"])
            matches_inserted += 1

        # Every fixture gets betting_status (eventBlocks override, else unblocked).
        status_written: set[int] = set()
        for match_id in match_ids:
            block = None
            for event_id, payload in event_blocks.items():
                if (
                    resolve_match_id_for_update(event_id, events_by_id, match_ids)
                    == match_id
                ):
                    block = payload
                    break
            cur.execute(
                """
                INSERT INTO betting_status (
                    site_id, match_id, state, partial_factor_ids, snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (site_id, match_id) DO UPDATE
                SET state = EXCLUDED.state,
                    partial_factor_ids = EXCLUDED.partial_factor_ids,
                    snapshot_id = EXCLUDED.snapshot_id
                """,
                (
                    site_id,
                    match_id,
                    normalize_fonbet_betting_state(
                        (block or {}).get("state", "unblocked")
                    ),
                    (block or {}).get("factors"),
                    snapshot_id,
                ),
            )
            status_written.add(match_id)

        known_match_ids = known_match_ids | match_ids
        score_update_ids = _collect_score_update_ids(
            match_ids,
            event_miscs,
            live_infos,
            event_blocks,
            events_by_id,
            known_match_ids,
        )
        scores_updated = 0

        for match_id in score_update_ids:
            if match_id in soft_finished_ids:
                continue
            misc, live = _merge_live_payload(
                match_id,
                event_miscs,
                live_infos,
                events_by_id,
                known_match_ids,
            )
            if misc or live:
                cur.execute(
                    """
                    INSERT INTO match_scores (
                        site_id, match_id, score1, score2, timer_seconds, timer_display,
                        timer_direction, live_delay, score_function, raw_scores,
                        subscores, timer_updated_at, snapshot_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    (
                        site_id,
                        match_id,
                        misc.get("score1"),
                        misc.get("score2"),
                        live.get("timerSeconds", misc.get("timerSeconds")),
                        live.get("timer"),
                        live.get("timerDirection", misc.get("timerDirection")),
                        misc.get("liveDelay"),
                        live.get("scoreFunction"),
                        psycopg2.extras.Json(live.get("scores")) if live.get("scores") else None,
                        psycopg2.extras.Json(live.get("subscores")) if live.get("subscores") else None,
                        millis_to_datetime(
                            live.get("timerTimestampMsec", misc.get("timerUpdateTimestampMsec"))
                        ),
                        snapshot_id,
                    ),
                )
                scores_updated += 1

            # Deltas may update status for known matches not re-listed in events[].
            if match_id not in match_ids:
                block = None
                for event_id, payload in event_blocks.items():
                    if (
                        resolve_match_id_for_update(
                            event_id, events_by_id, known_match_ids
                        )
                        == match_id
                    ):
                        block = payload
                        break
                if block:
                    cur.execute(
                        """
                        INSERT INTO betting_status (
                            site_id, match_id, state, partial_factor_ids, snapshot_id
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (site_id, match_id) DO UPDATE
                        SET state = EXCLUDED.state,
                            partial_factor_ids = EXCLUDED.partial_factor_ids,
                            snapshot_id = EXCLUDED.snapshot_id
                        """,
                        (
                            site_id,
                            match_id,
                            normalize_fonbet_betting_state(
                                block.get("state", "unknown")
                            ),
                            block.get("factors"),
                            snapshot_id,
                        ),
                    )
                    status_written.add(match_id)

        odds_rows: list[tuple[Any, ...]] = []
        for entry in custom_factors:
            market_event_id = entry["e"]
            root_match_id = find_root_match_id(market_event_id, events_by_id)
            if root_match_id is None:
                root_match_id = resolve_match_id_for_update(
                    market_event_id, events_by_id, known_match_ids
                )
            if root_match_id is None or root_match_id not in known_match_ids:
                continue
            if root_match_id in soft_finished_ids:
                continue
            if market_event_id != root_match_id:
                continue

            market_event = events_by_id.get(market_event_id, {})
            market_event_name = market_event.get("name") or "main"

            for factor in entry.get("factors", []):
                if not factor_is_allowed(factor["f"]):
                    continue
                # Suspended (v<=0): do not overwrite last recoverable odds.
                if not should_keep_last_odds(factor.get("v")):
                    continue
                line_param_raw = factor.get("p")
                odds_rows.append(
                    (
                        site_id,
                        root_match_id,
                        market_event_id,
                        market_event_name,
                        factor["f"],
                        factor["v"],
                        normalize_line_param(line_param_raw),
                        line_param_raw,
                        factor.get("pt"),
                        is_handicap_or_total(factor),
                        snapshot_id,
                    )
                )

        if odds_rows:
            allowed = sorted(allowed_factor_ids())
            affected_match_ids = list({row[1] for row in odds_rows})
            cur.execute(
                """
                DELETE FROM odds_lines
                WHERE site_id = %s
                  AND match_id = ANY(%s)
                  AND factor_id <> ALL(%s)
                """,
                (site_id, affected_match_ids, allowed),
            )
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO odds_lines (
                    site_id, match_id, market_event_id, market_event_name, factor_id, odds,
                    line_param, line_param_raw, line_param_text, is_handicap_total, snapshot_id
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

            # Odds can update known line matches without events[]/eventBlocks.
            for mid in affected_match_ids:
                if mid in status_written:
                    continue
                block = None
                for event_id, payload in event_blocks.items():
                    if (
                        resolve_match_id_for_update(
                            event_id, events_by_id, known_match_ids
                        )
                        == mid
                    ):
                        block = payload
                        break
                cur.execute(
                    """
                    INSERT INTO betting_status (
                        site_id, match_id, state, partial_factor_ids, snapshot_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (site_id, match_id) DO UPDATE
                    SET state = EXCLUDED.state,
                        partial_factor_ids = EXCLUDED.partial_factor_ids,
                        snapshot_id = EXCLUDED.snapshot_id
                    """,
                    (
                        site_id,
                        mid,
                        normalize_fonbet_betting_state(
                            (block or {}).get("state", "unblocked")
                        ),
                        (block or {}).get("factors"),
                        snapshot_id,
                    ),
                )
                status_written.add(mid)

        retention = apply_retention(
            cur,
            site_id,
            retain_snapshot_years=0 if keep_current_only else retain_snapshot_years,
            prune_matches_before_year=prune_matches_before_year,
        )
        matches_deleted = retention.get("matches_deleted", 0)
        snapshots_deleted = retention.get("snapshots_deleted", 0)
        leagues_deleted = 0
        sports_deleted = 0

        # Soft-finished lingerers (FT blocked @90', esports at ML, etc.).
        if keep_current_only and soft_finished_ids:
            removed_soft = delete_matches_by_ids(
                cur, site_id, soft_finished_ids, place="live"
            )
            matches_deleted += removed_soft

        # Prematch/line: drop kickoffs that are already in the past (no line poller
        # catalog prune yet — start_time is the authority).
        if keep_current_only and line_past_grace_hours is not None and line_past_grace_hours >= 0:
            removed_line = prune_past_place_matches(
                cur,
                site_id,
                place="line",
                grace_hours=int(line_past_grace_hours),
            )
            matches_deleted += removed_line

        # Full listLight snapshot = current live set; drop finished / absent matches.
        if keep_current_only and is_snapshot_packet(packet):
            live_keep = (active_live_match_ids(level_one_events) & match_ids) - soft_finished_ids
            if live_keep:
                removed = prune_absent_matches(cur, site_id, live_keep, place="live")
                matches_deleted += removed
                if removed:
                    orphans = prune_orphan_catalog(cur, site_id)
                    leagues_deleted = orphans.get("leagues_deleted", 0)
                    sports_deleted = orphans.get("sports_deleted", 0)
            elif soft_finished_ids:
                # Snapshot contained only finished lingerers — clear remaining live rows
                # that were soft-deleted above; nothing else to keep.
                pass

        if keep_current_only and (soft_finished_ids or matches_deleted):
            orphans = prune_orphan_catalog(cur, site_id)
            leagues_deleted = max(leagues_deleted, orphans.get("leagues_deleted", 0))
            sports_deleted = max(sports_deleted, orphans.get("sports_deleted", 0))

        if keep_current_only:
            snapshots_deleted += prune_snapshots_to_current(cur, site_id, snapshot_id)

    conn.commit()
    return snapshot_id, {
        "sport_reference": reference_count,
        "sports": sports_inserted,
        "leagues": leagues_inserted,
        "matches": matches_inserted,
        "scores_updated": scores_updated,
        "odds_lines": len(odds_rows),
        "matches_deleted": matches_deleted,
        "snapshots_deleted": snapshots_deleted,
        "leagues_deleted": leagues_deleted,
        "sports_deleted": sports_deleted,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import Fonbet JSON packet into PostgreSQL."
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default=str(Path(__file__).resolve().parent / "test.json"),
        help="Path to Fonbet JSON packet. Ignored when --poll.",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Poll Fonbet API every 5s (listLight, then list?version=packetVersion)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Poll interval in seconds (with --poll)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --poll: run listLight + one list update only",
    )
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Create tables from schema.sql before importing",
    )
    parser.add_argument(
        "--schema",
        default="schema.sql",
        help="Path to schema SQL file (default: schema.sql)",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="Bookmaker site name (default: SITE_NAME env or fonbet.com)",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Apply schema_migrate.sql (adds sports columns on existing DB)",
    )
    parser.add_argument(
        "--appendix",
        default=None,
        help="Path to Appendix A sports reference (default: docs/ or fonbet/)",
    )
    parser.add_argument(
        "--retain-snapshot-years",
        type=int,
        default=None,
        help="Keep snapshot audit rows for N calendar years (default: RETAIN_SNAPSHOT_YEARS or 1, 0=off)",
    )
    parser.add_argument(
        "--prune-matches-before-year",
        type=int,
        default=None,
        help="Delete matches with event_year before this year (optional)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.poll:
        from fonbet.config import FonbetApiConfig
        from fonbet.poll import run_poll

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
                snapshot_every=api_config.snapshot_every,
                line_past_grace_hours=api_config.line_past_grace_hours,
            )
        appendix_path = resolve_appendix_path(
            Path(args.appendix) if args.appendix else None
        )
        if appendix_path is None:
            raise SystemExit(
                "Appendix A not found. Place Appendix_A_sports_EN.md under docs/ "
                "or fonbet/, or pass --appendix PATH"
            )
        run_poll(
            site_name=args.site_name or db_config.site_name,
            db_config=db_config,
            api_config=api_config,
            appendix_path=appendix_path,
            init_schema_flag=args.init_schema,
            migrate_flag=args.migrate,
            max_iterations=2 if args.once else None,
            retain_snapshot_years=_retain_years(args, db_config),
            prune_matches_before_year=args.prune_matches_before_year,
        )
        return

    json_path = Path(args.json_file)
    schema_path = Path(args.schema)

    if not json_path.exists():
        raise SystemExit(f"JSON file not found: {json_path}")

    packet = load_packet(json_path)
    config = DatabaseConfig.from_env()
    site_name = args.site_name or config.site_name

    migrate_path = Path("schema_migrate.sql")

    with connect(config) as conn:
        if args.init_schema:
            if not schema_path.exists():
                raise SystemExit(f"Schema file not found: {schema_path}")
            init_schema(conn, schema_path)

        if args.migrate:
            if not migrate_path.exists():
                raise SystemExit(f"Migration file not found: {migrate_path}")
            run_migration(conn, migrate_path)

        appendix_path = resolve_appendix_path(
            Path(args.appendix) if args.appendix else None
        )
        snapshot_id, counts = import_packet(
            conn,
            packet,
            str(json_path.resolve()),
            site_name,
            appendix_path=appendix_path,
            retain_snapshot_years=_retain_years(args, config),
            prune_matches_before_year=args.prune_matches_before_year,
        )
        print(f"Imported snapshot {snapshot_id} for {site_name} from {json_path}")
        print(
            f"  sport_reference={counts['sport_reference']} sports={counts['sports']} "
            f"leagues={counts['leagues']} matches={counts['matches']} "
            f"scores={counts['scores_updated']} odds={counts['odds_lines']} "
            f"snapshots_deleted={counts['snapshots_deleted']} "
            f"matches_deleted={counts['matches_deleted']}"
        )


def _retain_years(args: argparse.Namespace, config: DatabaseConfig) -> int:
    if args.retain_snapshot_years is not None:
        return args.retain_snapshot_years
    return config.retain_snapshot_years


if __name__ == "__main__":
    main()
