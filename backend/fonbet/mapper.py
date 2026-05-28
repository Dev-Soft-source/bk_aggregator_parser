"""Map Fonbet JSON packets to normalized adapter DTOs."""

from __future__ import annotations

from typing import Any

from adapters.base import (
    Change,
    ChangeType,
    EventRef,
    OddsMarket,
    OddsOutcome,
    PacketSummary,
    SportRef,
    TournamentRef,
)
from fonbet.odds_config import (
    allowed_factor_ids,
    factor_is_allowed,
    ordered_factor_ids,
    sort_outcomes_by_config,
)
from fonbet.parsers import (
    build_sport_prefixes,
    build_sports_maps,
    find_root_match_id,
    is_handicap_or_total,
    normalize_line_param,
    parse_country_and_league,
    resolve_match_id_for_update,
    resolve_root_sport_id,
)


def _index_packet(packet: dict[str, Any]) -> dict[str, Any]:
    sports = packet.get("sports", [])
    events = packet.get("events", [])
    return {
        "sports": sports,
        "events": events,
        "events_by_id": {event["id"]: event for event in events},
        "event_miscs": {item["id"]: item for item in packet.get("eventMiscs", [])},
        "event_blocks": {item["eventId"]: item for item in packet.get("eventBlocks", [])},
        "live_infos": {item["eventId"]: item for item in packet.get("liveEventInfos", [])},
        "custom_factors": packet.get("customFactors", []),
        "packet_version": int(packet["packetVersion"]),
        "from_version": (
            int(packet["fromVersion"]) if packet.get("fromVersion") is not None else None
        ),
    }


def _level_one_match_ids(events: list[dict[str, Any]]) -> set[int]:
    return {event["id"] for event in events if event.get("level") == 1}


def resolve_known_match_ids(
    idx: dict[str, Any],
    known_match_ids: set[int] | None,
) -> set[int]:
    ids = _level_one_match_ids(idx["events"])
    if known_match_ids:
        ids |= known_match_ids
    return ids


def _merge_live_payload(
    match_id: int,
    event_miscs: dict[int, dict[str, Any]],
    live_infos: dict[int, dict[str, Any]],
    events_by_id: dict[int, dict[str, Any]],
    known: set[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    misc: dict[str, Any] = {}
    live: dict[str, Any] = {}

    for source in (event_miscs, live_infos):
        for eid, payload in source.items():
            if resolve_match_id_for_update(eid, events_by_id, known) == match_id:
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
    known: set[int],
) -> set[int]:
    update_ids = set(match_ids)
    candidate_ids = set(event_miscs) | set(live_infos) | set(event_blocks)
    for event_id in candidate_ids:
        root_id = resolve_match_id_for_update(event_id, events_by_id, known)
        if root_id is not None:
            update_ids.add(root_id)
    return update_ids


def discover_sports(packet: dict[str, Any]) -> list[SportRef]:
    return [
        SportRef(
            payload_id=sport["id"],
            name=sport.get("name") or "",
            alias=sport.get("alias"),
            sort_order=sport.get("sortOrder"),
        )
        for sport in packet.get("sports", [])
        if sport.get("kind") == "sport"
    ]


def discover_tournaments(packet: dict[str, Any]) -> list[TournamentRef]:
    sports = packet.get("sports", [])
    sports_by_id, _ = build_sports_maps(sports)
    sport_prefixes = build_sport_prefixes(sports)
    refs: list[TournamentRef] = []

    for segment in sports:
        if segment.get("kind") != "segment":
            continue
        root_sport_id = resolve_root_sport_id(segment["id"], sports_by_id)
        if root_sport_id is None:
            continue
        root_sport = sports_by_id.get(root_sport_id, {})
        country_name, _ = parse_country_and_league(
            segment["name"],
            sport_prefixes=sport_prefixes,
            root_sport_name=root_sport.get("name"),
        )
        refs.append(
            TournamentRef(
                payload_id=segment["id"],
                sport_payload_id=root_sport_id,
                name=segment["name"],
                country_name=country_name,
                region_id=segment.get("regionId"),
            )
        )
    return refs


def discover_events(packet: dict[str, Any], mode: str = "live") -> list[EventRef]:
    idx = _index_packet(packet)
    _, league_to_sport = build_sports_maps(idx["sports"])
    refs: list[EventRef] = []

    for event in idx["events"]:
        if event.get("level") != 1:
            continue
        place = event.get("place", "unknown")
        if mode == "live" and place not in ("live", "notActive"):
            continue
        if mode == "prematch" and place != "line":
            continue

        league_id = event.get("sportId")
        sport_id = league_to_sport.get(league_id) if league_id else None
        if sport_id is None:
            continue

        refs.append(
            EventRef(
                payload_id=event["id"],
                sport_payload_id=sport_id,
                league_payload_id=league_id,
                team1=event.get("team1"),
                team2=event.get("team2"),
                start_time_unix=event.get("startTime"),
                place=place,
                team1_id=event.get("team1Id"),
                team2_id=event.get("team2Id"),
                priority=event.get("priority"),
            )
        )
    return refs


def map_packet_to_changes(
    packet: dict[str, Any],
    *,
    known_match_ids: set[int] | None = None,
) -> list[Change]:
    idx = _index_packet(packet)
    known = resolve_known_match_ids(idx, known_match_ids)
    _, league_to_sport = build_sports_maps(idx["sports"])
    version = idx["packet_version"]
    from_version = idx["from_version"]
    changes: list[Change] = []

    for event in idx["events"]:
        if event.get("level") != 1:
            continue
        league_id = event.get("sportId")
        sport_id = league_to_sport.get(league_id) if league_id else None
        if sport_id is None:
            continue

        changes.append(
            Change(
                change_type=ChangeType.FIXTURE,
                match_payload_id=event["id"],
                packet_version=version,
                from_version=from_version,
                payload={
                    "league_payload_id": league_id,
                    "sport_payload_id": sport_id,
                    "team1": event.get("team1"),
                    "team2": event.get("team2"),
                    "team1_id": event.get("team1Id"),
                    "team2_id": event.get("team2Id"),
                    "start_time_unix": event.get("startTime"),
                    "place": event.get("place", "unknown"),
                    "priority": event.get("priority"),
                    "event_num": event.get("num"),
                },
            )
        )

    packet_match_ids = _level_one_match_ids(idx["events"])
    score_update_ids = _collect_score_update_ids(
        packet_match_ids,
        idx["event_miscs"],
        idx["live_infos"],
        idx["event_blocks"],
        idx["events_by_id"],
        known,
    )

    for match_id in score_update_ids:
        misc, live = _merge_live_payload(
            match_id,
            idx["event_miscs"],
            idx["live_infos"],
            idx["events_by_id"],
            known,
        )
        if misc or live:
            changes.append(
                Change(
                    change_type=ChangeType.SCORE,
                    match_payload_id=match_id,
                    packet_version=version,
                    from_version=from_version,
                    payload={
                        "score1": misc.get("score1"),
                        "score2": misc.get("score2"),
                        "timer_seconds": live.get("timerSeconds", misc.get("timerSeconds")),
                        "timer_display": live.get("timer"),
                        "timer_direction": live.get("timerDirection", misc.get("timerDirection")),
                        "live_delay": misc.get("liveDelay"),
                        "score_function": live.get("scoreFunction"),
                        "raw_scores": live.get("scores"),
                        "subscores": live.get("subscores"),
                        "timer_timestamp_msec": live.get(
                            "timerTimestampMsec", misc.get("timerUpdateTimestampMsec")
                        ),
                    },
                )
            )

        block = None
        for event_id, payload in idx["event_blocks"].items():
            if resolve_match_id_for_update(event_id, idx["events_by_id"], known) == match_id:
                block = payload
                break

        if block:
            changes.append(
                Change(
                    change_type=ChangeType.BETTING_STATUS,
                    match_payload_id=match_id,
                    packet_version=version,
                    from_version=from_version,
                    payload={
                        "state": block.get("state", "unknown"),
                        "partial_factor_ids": block.get("factors"),
                    },
                )
            )

    for entry in idx["custom_factors"]:
        market_event_id = entry["e"]
        root_match_id = find_root_match_id(market_event_id, idx["events_by_id"])
        if root_match_id is None:
            root_match_id = resolve_match_id_for_update(
                market_event_id, idx["events_by_id"], known
            )
        if root_match_id is None or root_match_id not in known:
            continue
        if market_event_id != root_match_id:
            continue

        market_event = idx["events_by_id"].get(market_event_id, {})
        market_event_name = market_event.get("name") or "main"

        outcomes: list[OddsOutcome] = []
        for factor in entry.get("factors", []):
            factor_id = factor["f"]
            if not factor_is_allowed(factor_id):
                continue
            line_param_raw = factor.get("p")
            outcomes.append(
                OddsOutcome(
                    factor_id=factor_id,
                    odds=float(factor["v"]),
                    line_param=normalize_line_param(line_param_raw),
                    line_param_raw=line_param_raw,
                    line_param_text=factor.get("pt"),
                    is_handicap_total=is_handicap_or_total(factor),
                )
            )
        outcomes = sort_outcomes_by_config(outcomes)
        slot_count = len(ordered_factor_ids())
        if len(outcomes) > slot_count:
            outcomes = outcomes[:slot_count]

        if not outcomes:
            continue

        market = OddsMarket(
            market_event_id=market_event_id,
            market_event_name=market_event_name,
            outcomes=tuple(outcomes),
        )
        changes.append(
            Change(
                change_type=ChangeType.ODDS,
                match_payload_id=root_match_id,
                packet_version=version,
                from_version=from_version,
                payload={
                    "market_event_id": market.market_event_id,
                    "market_event_name": market.market_event_name,
                    "outcomes": [
                        {
                            "factor_id": o.factor_id,
                            "odds": o.odds,
                            "line_param": o.line_param,
                            "line_param_raw": o.line_param_raw,
                            "line_param_text": o.line_param_text,
                            "is_handicap_total": o.is_handicap_total,
                        }
                        for o in market.outcomes
                    ],
                },
            )
        )

    return changes


def packet_summary(
    packet: dict[str, Any],
    *,
    known_match_ids: set[int] | None = None,
) -> PacketSummary:
    changes = map_packet_to_changes(packet, known_match_ids=known_match_ids)
    idx = _index_packet(packet)
    from_version = idx["from_version"]
    odds_outcomes = sum(
        len(c.payload.get("outcomes", []))
        for c in changes
        if c.change_type == ChangeType.ODDS
    )
    return PacketSummary(
        packet_version=idx["packet_version"],
        from_version=from_version,
        is_snapshot=from_version is None or from_version == 0,
        sports=len(discover_sports(packet)),
        leagues=len(discover_tournaments(packet)),
        fixtures=sum(1 for c in changes if c.change_type == ChangeType.FIXTURE),
        score_changes=sum(1 for c in changes if c.change_type == ChangeType.SCORE),
        betting_status_changes=sum(
            1 for c in changes if c.change_type == ChangeType.BETTING_STATUS
        ),
        odds_markets=sum(1 for c in changes if c.change_type == ChangeType.ODDS),
        odds_outcomes=odds_outcomes,
    )
