"""Map 1xBet Get1x2_VZip Value[] to normalized adapter Change objects."""

from __future__ import annotations

from typing import Any

from adapters.base import Change, ChangeType, PacketSummary
from lxbet_line.odds_config import (
    allowed_factor_ids,
    main_group_id,
    market_factor_maps,
    ordered_factor_ids,
)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outcomes_for_group(
    rows: list[Any],
    *,
    group_id: int,
    type_to_factor: dict[int, int],
) -> list[dict[str, Any]]:
    allowed = allowed_factor_ids()
    by_factor: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _as_int(row.get("G")) != group_id:
            continue
        outcome_type = _as_int(row.get("T"))
        if outcome_type is None:
            continue
        factor_id = type_to_factor.get(outcome_type)
        if factor_id is None or factor_id not in allowed:
            continue
        odds = _as_float(row.get("C"))
        if odds is None:
            continue
        by_factor[factor_id] = {
            "factor_id": factor_id,
            "odds": odds,
            "line_param_text": str(outcome_type),
            "is_handicap_total": False,
        }
    ordered: list[dict[str, Any]] = []
    for factor_id in ordered_factor_ids():
        if factor_id in by_factor:
            ordered.append(by_factor[factor_id])
    return ordered


def _extract_main_outcomes(event: dict[str, Any]) -> list[dict[str, Any]]:
    rows = event.get("E")
    if not isinstance(rows, list):
        return []

    for group_id, type_to_factor in market_factor_maps():
        outcomes = _outcomes_for_group(
            rows, group_id=group_id, type_to_factor=type_to_factor
        )
        factor_ids = {o["factor_id"] for o in outcomes}
        if 921 in factor_ids and 923 in factor_ids:
            return outcomes
    return []


def _parse_score(event: dict[str, Any]) -> tuple[int | None, int | None]:
    sc = event.get("SC")
    if not isinstance(sc, dict):
        return None, None
    fs = sc.get("FS")
    if not isinstance(fs, dict):
        return None, None
    has_s1 = "S1" in fs
    has_s2 = "S2" in fs
    if not has_s1 and not has_s2:
        return None, None
    score1 = _as_int(fs.get("S1")) if has_s1 else 0
    score2 = _as_int(fs.get("S2")) if has_s2 else 0
    if score1 is None:
        score1 = 0
    if score2 is None:
        score2 = 0
    return score1, score2


def _timer_payload(event: dict[str, Any]) -> dict[str, Any]:
    sc = event.get("SC")
    if not isinstance(sc, dict):
        return {}
    payload: dict[str, Any] = {}
    display = _as_str(sc.get("S")) or _as_str(sc.get("CPS"))
    if display:
        payload["timer_display"] = display
    seconds = _as_int(sc.get("TS"))
    if seconds is not None:
        payload["timer_seconds"] = seconds
    return payload


def betting_state(event: dict[str, Any], outcomes: list[dict[str, Any]]) -> str:
    if len(outcomes) >= 2:
        return "unblocked"
    return "blocked"


def map_packet_to_changes(
    packet: dict[str, Any],
    *,
    version: int,
) -> list[Change]:
    value = packet.get("Value")
    if not isinstance(value, list):
        return []

    changes: list[Change] = []
    for event in value:
        if not isinstance(event, dict):
            continue
        event_id = _as_int(event.get("I"))
        if event_id is None:
            continue
        team1 = _as_str(event.get("O1")) or _as_str(event.get("O1E"))
        if not team1:
            continue
        team2 = _as_str(event.get("O2")) or _as_str(event.get("O2E"))

        outcomes = _extract_main_outcomes(event)
        # Skip blocked / empty main market — do not persist fixture without odds.
        factor_ids = {o["factor_id"] for o in outcomes}
        if 921 not in factor_ids or 923 not in factor_ids:
            continue

        sport_id = _as_int(event.get("SI")) or 0
        league_id = _as_int(event.get("LI")) or 0
        sport_name = (
            _as_str(event.get("SN"))
            or _as_str(event.get("SE"))
            or (f"Sport {sport_id}" if sport_id else "Unknown")
        )
        league_name = (
            _as_str(event.get("L"))
            or _as_str(event.get("LE"))
            or (f"League {league_id}" if league_id else "Unknown")
        )
        start_time_unix = _as_int(event.get("S"))

        changes.append(
            Change(
                change_type=ChangeType.FIXTURE,
                match_payload_id=event_id,
                packet_version=version,
                payload={
                    "sport_payload_id": sport_id,
                    "sport_name": sport_name,
                    "league_payload_id": league_id,
                    "league_name": league_name,
                    "team1": team1,
                    "team2": team2,
                    "start_time_unix": start_time_unix,
                    "place": "line",
                    "priority": _as_int(event.get("R")),
                    "country_name": _as_str(event.get("CN")),
                },
            )
        )

        score1, score2 = _parse_score(event)
        timer = _timer_payload(event)
        sc = event.get("SC") if isinstance(event.get("SC"), dict) else None
        if score1 is not None or score2 is not None or timer:
            changes.append(
                Change(
                    change_type=ChangeType.SCORE,
                    match_payload_id=event_id,
                    packet_version=version,
                    payload={
                        "score1": score1,
                        "score2": score2,
                        "raw_scores": sc,
                        **timer,
                    },
                )
            )

        changes.append(
            Change(
                change_type=ChangeType.BETTING_STATUS,
                match_payload_id=event_id,
                packet_version=version,
                payload={"state": betting_state(event, outcomes)},
            )
        )

        changes.append(
            Change(
                change_type=ChangeType.ODDS,
                match_payload_id=event_id,
                packet_version=version,
                payload={
                    "market_id": main_group_id(),
                    "market_event_id": event_id,
                    "market_event_name": "main",
                    "outcomes": outcomes,
                },
            )
        )

    return changes


def packet_summary(packet: dict[str, Any], *, version: int) -> PacketSummary:
    value = packet.get("Value")
    events = value if isinstance(value, list) else []
    odds_markets = 0
    odds_outcomes = 0
    sports: set[int] = set()
    leagues: set[int] = set()
    fixtures = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        outcomes = _extract_main_outcomes(event)
        factor_ids = {o["factor_id"] for o in outcomes}
        if 921 not in factor_ids or 923 not in factor_ids:
            continue
        fixtures += 1
        sid = _as_int(event.get("SI"))
        lid = _as_int(event.get("LI"))
        if sid is not None:
            sports.add(sid)
        if lid is not None:
            leagues.add(lid)
        odds_markets += 1
        odds_outcomes += len(outcomes)
    return PacketSummary(
        packet_version=version,
        from_version=None,
        is_snapshot=True,
        sports=len(sports),
        leagues=len(leagues),
        fixtures=fixtures,
        score_changes=0,
        betting_status_changes=0,
        odds_markets=odds_markets,
        odds_outcomes=odds_outcomes,
    )
