"""Map Liga Stavok JSON snapshots to normalized adapter DTOs."""

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
from ligastavok.odds_config import (
    main_market_types,
    ordered_outcome_keys,
    outcome_key_is_allowed,
)


def extract_events(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap API envelope: { result: { data: [...] } } or bare list."""
    if isinstance(packet, list):
        return packet
    result = packet.get("result")
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        return result["data"]
    if isinstance(packet.get("data"), list):
        return packet["data"]
    return []


def packet_version(packet: dict[str, Any]) -> int:
    result = packet.get("result")
    if isinstance(result, dict) and result.get("ts") is not None:
        return int(result["ts"])
    if packet.get("ts") is not None:
        return int(packet["ts"])
    events = extract_events(packet)
    if events and events[0].get("hash") is not None:
        return int(events[0]["hash"])
    return 0


def _place(ns: str | None) -> str:
    if ns == "live":
        return "live"
    if ns == "prematch":
        return "line"
    return ns or "unknown"


def _start_time_unix(item: dict[str, Any]) -> int | None:
    if item.get("gameTs") is not None:
        return int(item["gameTs"]) // 1000
    return None


def _event_block(item: dict[str, Any]) -> dict[str, Any]:
    event = item.get("event")
    return event if isinstance(event, dict) else {}


def _ids_block(item: dict[str, Any]) -> dict[str, Any]:
    ids = item.get("ids")
    return ids if isinstance(ids, dict) else {}


def discover_sports(packet: dict[str, Any]) -> list[SportRef]:
    seen: dict[int, SportRef] = {}
    for item in extract_events(packet):
        game_id = item.get("gameId")
        if game_id is None:
            continue
        gid = int(game_id)
        if gid not in seen:
            seen[gid] = SportRef(
                payload_id=gid,
                name=str(item.get("gameTitle") or item.get("title") or ""),
            )
    return list(seen.values())


def discover_tournaments(packet: dict[str, Any]) -> list[TournamentRef]:
    seen: dict[int, TournamentRef] = {}
    for item in extract_events(packet):
        ids = _ids_block(item)
        event = _event_block(item)
        tournament_id = ids.get("tournamentId")
        game_id = item.get("gameId")
        if tournament_id is None or game_id is None:
            continue
        tid = int(tournament_id)
        if tid in seen:
            continue
        seen[tid] = TournamentRef(
            payload_id=tid,
            sport_payload_id=int(game_id),
            name=str(event.get("tournamentTitle") or event.get("topicTitle") or ""),
            country_name=event.get("categoryTitle"),
        )
    return list(seen.values())


def discover_events(packet: dict[str, Any], mode: str = "live") -> list[EventRef]:
    refs: list[EventRef] = []
    for item in extract_events(packet):
        place = _place(item.get("ns"))
        if mode == "live" and place != "live":
            continue
        if mode == "prematch" and place != "line":
            continue

        ids = _ids_block(item)
        event = _event_block(item)
        match_id = item.get("id")
        game_id = item.get("gameId")
        tournament_id = ids.get("tournamentId")
        if match_id is None or game_id is None or tournament_id is None:
            continue

        refs.append(
            EventRef(
                payload_id=int(match_id),
                sport_payload_id=int(game_id),
                league_payload_id=int(tournament_id),
                team1=event.get("team1"),
                team2=event.get("team2"),
                start_time_unix=_start_time_unix(item),
                place=place,
                priority=(item.get("priority") or {}).get("event"),
            )
        )
    return refs


def _main_win_market(item: dict[str, Any]) -> dict[str, Any] | None:
    markets = item.get("markets") or {}
    for target_type in main_market_types():
        candidates = [
            m
            for m in markets.values()
            if isinstance(m, dict) and m.get("type") == target_type and not m.get("locked")
        ]
        if candidates:
            candidates.sort(key=lambda m: m.get("position") or 0)
            return candidates[0]
    return None


def _betting_state(item: dict[str, Any]) -> str:
    if item.get("corrupted"):
        return "blocked"
    if not item.get("hasUnlocked", True):
        return "blocked"
    market = _main_win_market(item)
    if market and market.get("locked"):
        return "partial"
    return "unblocked"


def _parse_match_time_minutes(match_time: Any) -> int | None:
    """Parse event.matchTime (minutes, optionally with stoppage e.g. 45+2)."""
    if match_time is None:
        return None
    text = str(match_time).strip().rstrip("'")
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "+" in text:
        base, extra = text.split("+", 1)
        try:
            return int(base) + int(extra)
        except ValueError:
            return None
    return None


def _score_payload(item: dict[str, Any]) -> dict[str, Any]:
    event = _event_block(item)
    scores = item.get("scores") or {}
    total = scores.get("total") or {}
    current = scores.get("current") or {}
    status = event.get("status")

    def _parse_score(block: dict[str, Any]) -> tuple[int | None, int | None]:
        if not block:
            return None, None
        s1, s2 = block.get("ScoreTeam1"), block.get("ScoreTeam2")
        try:
            return int(s1) if s1 is not None else None, int(s2) if s2 is not None else None
        except (TypeError, ValueError):
            return None, None

    score1, score2 = _parse_score(total)
    if score1 is None and score2 is None:
        score1, score2 = _parse_score(current)

    match_time = event.get("matchTime")
    timer_display = event.get("statusTranslated") or status
    match_minutes = _parse_match_time_minutes(match_time)
    if match_time is not None:
        timer_display = f"{match_time}'"
    timer_seconds = match_minutes * 60 if match_minutes is not None else None

    return {
        "score1": score1,
        "score2": score2,
        "timer_display": timer_display,
        "timer_seconds": timer_seconds,
        "score_function": str(status) if status is not None else None,
        "status": status,
        "status_translated": event.get("statusTranslated"),
        "raw_scores": scores,
    }


def _odds_outcomes(item: dict[str, Any]) -> list[OddsOutcome]:
    market = _main_win_market(item)
    if not market:
        return []

    market_key = f"_{market['id']}" if not str(market["id"]).startswith("_") else str(market["id"])
    market_id_ref = market.get("id")
    outcomes_raw = item.get("outcomes") or {}
    keys_order = {k: i for i, k in enumerate(ordered_outcome_keys())}
    picked: list[tuple[int, OddsOutcome]] = []

    for outcome in outcomes_raw.values():
        if not isinstance(outcome, dict):
            continue
        if outcome.get("locked") or outcome.get("corrupted"):
            continue
        ref = outcome.get("marketId")
        if ref != market_key and ref != market_id_ref:
            continue
        outcome_key = str(outcome.get("outcomeKey") or "")
        if not outcome_key_is_allowed(outcome_key):
            continue
        value = outcome.get("value")
        fac_id = outcome.get("facId")
        if value is None or fac_id is None:
            continue
        picked.append(
            (
                keys_order.get(outcome_key, 99),
                OddsOutcome(
                    factor_id=int(fac_id),
                    odds=float(value),
                    line_param_text=outcome.get("adValue"),
                    is_handicap_total=False,
                ),
            )
        )

    picked.sort(key=lambda pair: pair[0])
    return [o for _, o in picked[: len(ordered_outcome_keys())]]


def map_event_to_changes(
    item: dict[str, Any],
    *,
    packet_version: int,
    from_version: int | None = None,
) -> list[Change]:
    match_id = item.get("id")
    if match_id is None:
        return []

    ids = _ids_block(item)
    event = _event_block(item)
    game_id = item.get("gameId")
    tournament_id = ids.get("tournamentId")
    if game_id is None or tournament_id is None:
        return []

    mid = int(match_id)
    changes: list[Change] = [
        Change(
            change_type=ChangeType.FIXTURE,
            match_payload_id=mid,
            packet_version=packet_version,
            from_version=from_version,
            payload={
                "sport_payload_id": int(game_id),
                "league_payload_id": int(tournament_id),
                "sport_name": item.get("gameTitle"),
                "country_name": event.get("categoryTitle"),
                "league_name": event.get("tournamentTitle"),
                "team1": event.get("team1"),
                "team2": event.get("team2"),
                "start_time_unix": _start_time_unix(item),
                "place": _place(item.get("ns")),
                "priority": (item.get("priority") or {}).get("event"),
                "ext_id": event.get("extId"),
            },
        )
    ]

    score_payload = _score_payload(item)
    if any(
        score_payload.get(k) is not None
        for k in ("score1", "score2", "timer_display", "status")
    ):
        changes.append(
            Change(
                change_type=ChangeType.SCORE,
                match_payload_id=mid,
                packet_version=packet_version,
                from_version=from_version,
                payload=score_payload,
            )
        )

    changes.append(
        Change(
            change_type=ChangeType.BETTING_STATUS,
            match_payload_id=mid,
            packet_version=packet_version,
            from_version=from_version,
            payload={"state": _betting_state(item)},
        )
    )

    outcomes = _odds_outcomes(item)
    if outcomes:
        market = _main_win_market(item)
        market_name = market.get("title") if market else "main"
        market = OddsMarket(
            market_event_id=mid,
            market_event_name=str(market_name) if market_name else None,
            outcomes=tuple(outcomes),
        )
        changes.append(
            Change(
                change_type=ChangeType.ODDS,
                match_payload_id=mid,
                packet_version=packet_version,
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


def map_packet_to_changes(
    packet: dict[str, Any],
    *,
    known_match_ids: set[int] | None = None,
) -> list[Change]:
    version = packet_version(packet)
    events = extract_events(packet)
    if known_match_ids:
        events = [e for e in events if int(e["id"]) in known_match_ids]

    changes: list[Change] = []
    for item in events:
        changes.extend(map_event_to_changes(item, packet_version=version, from_version=None))
    return changes


def packet_summary(
    packet: dict[str, Any],
    *,
    known_match_ids: set[int] | None = None,
) -> PacketSummary:
    changes = map_packet_to_changes(packet, known_match_ids=known_match_ids)
    odds_outcomes = sum(
        len(c.payload.get("outcomes", []))
        for c in changes
        if c.change_type == ChangeType.ODDS
    )
    return PacketSummary(
        packet_version=packet_version(packet),
        from_version=None,
        is_snapshot=True,
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
