"""Map Betcity feed state to normalized adapter Change objects."""

from __future__ import annotations

from typing import Any

from adapters.base import Change, ChangeType, PacketSummary
from betcity_live.catalog import BetcityCatalog, CatalogEvent
from betcity_live.odds_config import (
    allowed_factor_ids,
    factor_for_outcome_key,
    main_block_key,
    main_market_id,
    ordered_factor_ids,
)
from betcity_live.state import BetcityFeedState, EventState


def _parse_score(
    event: EventState,
    meta: CatalogEvent | None = None,
) -> tuple[int | None, int | None]:
    """
    Resolve match score.

    Prefer the HTTP on-air catalog: WS sports deltas often omit or stale
    sc_ev_cmx, which produced blank (—) or outdated scores in the UI.
    """
    if meta is not None and meta.score1 is not None and meta.score2 is not None:
        return meta.score1, meta.score2

    cmx = event.fields.get("sc_ev_cmx")
    if isinstance(cmx, dict):
        main = cmx.get("main")
        if isinstance(main, list) and main:
            first = main[0]
            if isinstance(first, list) and len(first) >= 2:
                try:
                    return int(first[0]), int(first[1])
                except (TypeError, ValueError):
                    pass
    sc = event.fields.get("sc_ev")
    if isinstance(sc, str) and ":" in sc:
        left, right = sc.split(":", 1)
        try:
            return int(left.strip()), int(right.strip())
        except ValueError:
            return None, None
    return None, None


def _timer_payload(
    event: EventState,
    meta: CatalogEvent | None = None,
) -> dict[str, Any]:
    timer = event.fields.get("m_tmr")
    payload: dict[str, Any] = {}
    if isinstance(timer, dict):
        tmr = timer.get("tmr")
        if tmr is not None:
            try:
                payload["timer_seconds"] = int(tmr)
            except (TypeError, ValueError):
                pass
        fmt = timer.get("format")
        if fmt == "mm:ss" and payload.get("timer_seconds") is not None:
            secs = int(payload["timer_seconds"])
            payload["timer_display"] = f"{secs // 60:02d}:{secs % 60:02d}"
        # Betcity: is_run=1 → clock ticking; 0 → frozen (HT / stopped).
        is_run = timer.get("is_run")
        if is_run is not None:
            try:
                payload["score_function"] = "run" if int(is_run) == 1 else "stop"
            except (TypeError, ValueError):
                pass
    minute = event.fields.get("min")
    if minute is None and meta is not None:
        minute = meta.minute
    if minute is not None and "timer_display" not in payload:
        try:
            mins = int(minute)
            payload["timer_display"] = f"{mins:02d}:00"
            payload["timer_seconds"] = mins * 60
            # Whole-minute catalog fallback — let the UI tick until WS m_tmr arrives.
            payload.setdefault("score_function", "run")
        except (TypeError, ValueError):
            payload["timer_display"] = str(minute)
    return payload


def _extract_main_outcomes(event: EventState) -> list[dict[str, Any]]:
    market_id = str(main_market_id())
    market = event.main_markets.get(market_id)
    if not isinstance(market, dict):
        return []

    block_key = main_block_key()
    allowed = allowed_factor_ids()
    by_factor: dict[int, dict[str, Any]] = {}

    data = market.get("data") or {}
    if not isinstance(data, dict):
        return []

    for _row_key, row in data.items():
        if not isinstance(row, dict):
            continue
        blocks = row.get("blocks") or {}
        if not isinstance(blocks, dict):
            continue
        block = blocks.get(block_key)
        if not isinstance(block, dict):
            continue
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


def _main_wm_block(event: EventState) -> dict[str, Any] | None:
    market = event.main_markets.get(str(main_market_id()))
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


def _outcome_st_values(block: dict[str, Any]) -> list[int]:
    """Collect st flags for P1/P2 (and other mapped) outcomes."""
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


def is_blocked(event: EventState, meta: CatalogEvent | None = None) -> bool:
    """True when Betcity marks the main line as not open for betting."""
    return betting_state(event, meta) == "blocked"


def betting_state(
    event: EventState,
    meta: CatalogEvent | None = None,
) -> str:
    """
    Resolve UI betting state from the live main market.

    Betcity market/outcome ``st``:
      - 2 = open (accepting bets)
      - 1 = locked / suspended

    Do **not** use catalog ``status_ev`` — most live events have status_ev=0
    while still open, which falsely marked almost every row as Blocked.
    """
    del meta  # names/scores only; not used for betting lock
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

    # No market snapshot yet — treat as open if we already have priced odds.
    if len(_extract_main_outcomes(event)) >= 2:
        return "unblocked"
    return "unblocked"


def has_catalog_names(meta: CatalogEvent | None) -> bool:
    """Require real team/league names — never persist Event/League placeholders."""
    if meta is None:
        return False
    if not (meta.team1 and str(meta.team1).strip()):
        return False
    if not (meta.league_name and str(meta.league_name).strip()):
        return False
    return True


def _fixture_names(
    event: EventState,
    meta: CatalogEvent,
) -> dict[str, Any]:
    sport_id = int(event.sport_id or meta.sport_id or 0)
    league_id = int(event.championship_id or meta.championship_id or 0)
    return {
        "sport_payload_id": sport_id,
        "sport_name": meta.sport_name or (f"Sport {sport_id}" if sport_id else "Unknown"),
        "league_payload_id": league_id,
        "league_name": meta.league_name,
        "team1": meta.team1,
        "team2": meta.team2,
        "start_time_unix": meta.start_time_unix,
        "place": "live",
        "priority": None,
    }


def map_state_to_changes(
    state: BetcityFeedState,
    *,
    version: int,
    catalog: BetcityCatalog | None = None,
) -> list[Change]:
    changes: list[Change] = []
    for event in state.events.values():
        meta = catalog.get(event.event_id) if catalog is not None else None
        # Skip unnamed WS-only rows (Event {id} / League {id}).
        if not has_catalog_names(meta):
            continue
        assert meta is not None

        changes.append(
            Change(
                change_type=ChangeType.FIXTURE,
                match_payload_id=event.event_id,
                packet_version=version,
                payload=_fixture_names(event, meta),
            )
        )

        score1, score2 = _parse_score(event, meta)
        timer = _timer_payload(event, meta)
        raw_scores = (
            meta.raw_scores
            or event.fields.get("sc_ev_cmx")
        )
        if score1 is not None or score2 is not None or timer:
            changes.append(
                Change(
                    change_type=ChangeType.SCORE,
                    match_payload_id=event.event_id,
                    packet_version=version,
                    payload={
                        "score1": score1,
                        "score2": score2,
                        "raw_scores": raw_scores,
                        **timer,
                    },
                )
            )

        changes.append(
            Change(
                change_type=ChangeType.BETTING_STATUS,
                match_payload_id=event.event_id,
                packet_version=version,
                payload={"state": betting_state(event, meta)},
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


def state_summary(state: BetcityFeedState) -> PacketSummary:
    fixtures = len(state.events)
    score_changes = 0
    odds_markets = 0
    odds_outcomes = 0
    for event in state.events.values():
        s1, s2 = _parse_score(event)
        if s1 is not None or s2 is not None or event.fields.get("m_tmr"):
            score_changes += 1
        outcomes = _extract_main_outcomes(event)
        if outcomes:
            odds_markets += 1
            odds_outcomes += len(outcomes)
    return PacketSummary(
        packet_version=int(state.last_md or 0),
        from_version=None,
        is_snapshot=state.frame_count <= 2,
        sports=len({e.sport_id for e in state.events.values() if e.sport_id}),
        leagues=len(
            {e.championship_id for e in state.events.values() if e.championship_id}
        ),
        fixtures=fixtures,
        score_changes=score_changes,
        betting_status_changes=0,
        odds_markets=odds_markets,
        odds_outcomes=odds_outcomes,
    )


def map_packet_to_changes(
    packet: dict[str, Any],
    *,
    version: int | None = None,
    catalog: BetcityCatalog | None = None,
) -> list[Change]:
    """Convenience: apply one packet to a fresh state and map."""
    state = BetcityFeedState()
    state.apply_frame(packet)
    ver = version if version is not None else int(packet.get("md") or 0)
    return map_state_to_changes(state, version=ver, catalog=catalog)
