"""Map Betcity prematch line state to normalized adapter Change objects."""

from __future__ import annotations

from typing import Any

from adapters.base import Change, ChangeType, PacketSummary
from betcity_line.odds_config import (
    allowed_factor_ids,
    factor_for_outcome_key,
    main_block_key,
    main_market_id,
    ordered_factor_ids,
)
from betcity_line.state import BetcityLineState, LineEvent


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _main_wm_block(event: LineEvent) -> dict[str, Any] | None:
    main = event.fields.get("main")
    if not isinstance(main, dict):
        return None
    market = main.get(str(main_market_id())) or main.get(main_market_id())
    if not isinstance(market, dict):
        return None
    data = market.get("data") or {}
    if not isinstance(data, dict):
        return None
    block_key = main_block_key()
    for row in data.values():
        if not isinstance(row, dict):
            continue
        blocks = row.get("blocks") or {}
        if not isinstance(blocks, dict):
            continue
        block = blocks.get(block_key)
        if isinstance(block, dict):
            return block
    return None


def _extract_main_outcomes(event: LineEvent) -> list[dict[str, Any]]:
    block = _main_wm_block(event)
    if not isinstance(block, dict):
        return []

    allowed = allowed_factor_ids()
    by_factor: dict[int, dict[str, Any]] = {}
    for outcome_key, outcome in block.items():
        if outcome_key == "st" or not isinstance(outcome, dict):
            continue
        factor_id = factor_for_outcome_key(str(outcome_key))
        if factor_id is None or factor_id not in allowed:
            continue
        kf = outcome.get("kf")
        if kf is None:
            continue
        try:
            odds = float(kf)
        except (TypeError, ValueError):
            continue
        by_factor[factor_id] = {
            "factor_id": factor_id,
            "odds": odds,
            "line_param_text": str(outcome_key),
            "is_handicap_total": False,
        }

    ordered: list[dict[str, Any]] = []
    for factor_id in ordered_factor_ids():
        if factor_id in by_factor:
            ordered.append(by_factor[factor_id])
    return ordered


def _outcome_st_values(block: dict[str, Any]) -> list[int]:
    allowed = allowed_factor_ids()
    values: list[int] = []
    for outcome_key, outcome in block.items():
        if outcome_key == "st" or not isinstance(outcome, dict):
            continue
        factor_id = factor_for_outcome_key(str(outcome_key))
        if factor_id is None or factor_id not in allowed:
            continue
        raw = outcome.get("st")
        if raw is None:
            continue
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return values


def betting_state(event: LineEvent) -> str:
    """Wm outcome/block st: 2=open, 1=locked."""
    block = _main_wm_block(event)
    if block is not None:
        outcome_states = _outcome_st_values(block)
        if outcome_states:
            open_n = sum(1 for s in outcome_states if s == 2)
            locked_n = sum(1 for s in outcome_states if s != 2)
            if open_n and locked_n:
                return "partial"
            if open_n:
                return "unblocked"
            return "blocked"
        raw_block_st = block.get("st")
        if raw_block_st is not None:
            try:
                return "unblocked" if int(raw_block_st) == 2 else "blocked"
            except (TypeError, ValueError):
                pass
    if len(_extract_main_outcomes(event)) >= 2:
        return "unblocked"
    return "unblocked"


def has_team_names(event: LineEvent) -> bool:
    team1 = _as_str(event.fields.get("name_ht"))
    return bool(team1)


def map_state_to_changes(
    state: BetcityLineState,
    *,
    version: int,
) -> list[Change]:
    changes: list[Change] = []
    for event in state.events.values():
        if not has_team_names(event):
            continue

        team1 = _as_str(event.fields.get("name_ht"))
        team2 = _as_str(event.fields.get("name_at"))
        sport_id = int(event.sport_id or 0)
        league_id = int(event.championship_id or 0)
        sport_name = event.sport_name or (f"Sport {sport_id}" if sport_id else "Unknown")
        league_name = event.league_name or (
            f"League {league_id}" if league_id else "Unknown"
        )
        start_time_unix = None
        raw_date = event.fields.get("date_ev")
        if raw_date is not None:
            try:
                start_time_unix = int(raw_date)
            except (TypeError, ValueError):
                start_time_unix = None

        changes.append(
            Change(
                change_type=ChangeType.FIXTURE,
                match_payload_id=event.event_id,
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
                    "priority": event.fields.get("order"),
                },
            )
        )

        changes.append(
            Change(
                change_type=ChangeType.BETTING_STATUS,
                match_payload_id=event.event_id,
                packet_version=version,
                payload={"state": betting_state(event)},
            )
        )

        outcomes = _extract_main_outcomes(event)
        if len(outcomes) >= 2:
            changes.append(
                Change(
                    change_type=ChangeType.ODDS,
                    match_payload_id=event.event_id,
                    packet_version=version,
                    payload={
                        "market_id": main_market_id(),
                        "market_event_id": event.event_id,
                        "market_event_name": "main",
                        "outcomes": outcomes,
                    },
                )
            )
    return changes


def state_summary(state: BetcityLineState) -> PacketSummary:
    odds_markets = 0
    odds_outcomes = 0
    for event in state.events.values():
        outcomes = _extract_main_outcomes(event)
        if outcomes:
            odds_markets += 1
            odds_outcomes += len(outcomes)
    return PacketSummary(
        packet_version=int(state.last_ntime or 0),
        from_version=None,
        is_snapshot=state.packet_count <= 1,
        sports=len({e.sport_id for e in state.events.values() if e.sport_id}),
        leagues=len(
            {e.championship_id for e in state.events.values() if e.championship_id}
        ),
        fixtures=len(state.events),
        score_changes=0,
        betting_status_changes=0,
        odds_markets=odds_markets,
        odds_outcomes=odds_outcomes,
    )


def map_packet_to_changes(
    packet: dict[str, Any],
    *,
    version: int | None = None,
    replace: bool = True,
) -> list[Change]:
    state = BetcityLineState()
    state.apply_packet(packet, replace=replace)
    ver = version
    if ver is None:
        ver = int(state.last_ntime or 0)
    return map_state_to_changes(state, version=ver)
