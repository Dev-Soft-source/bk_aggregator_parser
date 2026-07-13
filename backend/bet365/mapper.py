"""Map bet365 ZAP state to normalized adapter Change objects."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from adapters.base import Change, ChangeType, EventRef, OddsOutcome, PacketSummary
from bet365.odds_config import (
    OUTCOME_FACTOR_BY_OR,
    import_all_from_socket,
    is_primary_market,
    main_market_id,
    main_market_name,
)
from bet365.state import EventState, SelectionState, ZapFeedState
from bet365.zap_parse import field_int, parse_match_teams, sport_class_from_event_fields

_LONDON = ZoneInfo("Europe/London")


def _parse_score(score: str) -> tuple[int | None, int | None]:
    text = (score or "").strip()
    if "-" not in text:
        return None, None
    left, right = text.split("-", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None, None


def _parse_tu_epoch(tu: str | None) -> int | None:
    """Bet365 TU: YearMonthDayHourMinSecs in Europe/London."""
    if not tu:
        return None
    raw = str(tu).strip()
    if len(raw) < 14 or not raw[:14].isdigit():
        return None
    try:
        dt = datetime.strptime(raw[:14], "%Y%m%d%H%M%S").replace(tzinfo=_LONDON)
        return int(dt.timestamp())
    except ValueError:
        return None


def _timer_payload(event: EventState) -> dict[str, Any]:
    """
    Bet365 clock: TM=mins, TS=secs, TT=ticking, TU=period sync time.

    Frontend advances timer_seconds since timer_updated_at. We must:
    - run when the match clock is playing (TT=1, or live with TT unknown)
    - stop on break (TT=0)
    - prefer absolute elapsed when TU is present
    """
    tm = event.minute
    ts = event.timer_secs
    if tm is None and ts is None:
        return {}

    mins = int(tm or 0)
    secs = int(ts or 0)
    base = max(0, mins * 60 + secs)

    if event.timer_ticking is False:
        ticking = False
    elif event.timer_ticking is True:
        ticking = True
    else:
        # TT often omitted on EV snapshots — assume running for in-play.
        ticking = bool(event.live)

    tu_epoch = _parse_tu_epoch(event.timer_tu or event.fields.get("TU"))

    if ticking and tu_epoch is not None:
        # passed = (NOW - TU) + TM*60 + TS
        passed = max(0, int(time.time()) - tu_epoch) + base
        display_min = passed // 60
        return {
            "minute": display_min,
            "timer_seconds": passed,
            "timer_display": f"{display_min}'",
            "score_function": "run",
        }

    display_min = mins if tm is not None else base // 60
    return {
        "minute": display_min,
        "timer_seconds": base,
        "timer_display": f"{display_min}'",
        "score_function": "run" if ticking else "stop",
    }


def _sport_payload_id(event: EventState, state: ZapFeedState) -> int:
    sport_class = state.sport_class_for(event)
    if sport_class is not None:
        return sport_class
    return 0


def _event_ref(event: EventState, state: ZapFeedState) -> EventRef:
    team1, team2 = event.team1, event.team2
    if not team1 and not team2 and event.name:
        team1, team2 = parse_match_teams(event.name)
    league_id = int(event.fields.get("C2") or event.fields.get("C3") or 0)
    return EventRef(
        payload_id=event.fi,
        sport_payload_id=_sport_payload_id(event, state),
        league_payload_id=league_id,
        team1=team1,
        team2=team2,
        start_time_unix=None,
        place="live" if event.live else "line",
    )


def _looks_like_match_result(
    selections: list[SelectionState],
    market_name: str | None,
) -> bool:
    """Two/three-way winner market (not handicap/total)."""
    if market_name:
        lower = market_name.lower()
        if any(
            token in lower
            for token in (
                "over",
                "under",
                "handicap",
                "total",
                "corner",
                "card",
                "booking",
                "game ",
                "set ",
                "point",
            )
        ):
            return False
    if any(sel.fields.get("HA") for sel in selections):
        return False
    orders = sorted(s.order for s in selections if s.order is not None)
    return orders in ([0, 1], [0, 1, 2])


def _use_standard_factors(
    market_id: int,
    market_name: str | None,
    selections: list[SelectionState],
) -> bool:
    if is_primary_market(market_name) or market_id == main_market_id():
        return True
    return _looks_like_match_result(selections, market_name)


def _display_factor_id(order: int | None, n_outcomes: int) -> int | None:
    if order is None:
        return None
    if n_outcomes == 2:
        return {0: 921, 1: 923}.get(order)
    return OUTCOME_FACTOR_BY_OR.get(order)


def _selection_outcome_dict(
    sel: SelectionState,
    *,
    market_id: int,
    market_name: str | None,
    standard_factors: bool,
    n_outcomes: int,
) -> dict[str, Any] | None:
    if sel.odds_decimal is None or sel.suspended:
        return None
    pa_id = field_int(sel.fields, "ID")
    factor_id: int | None = None
    if standard_factors:
        factor_id = _display_factor_id(sel.order, n_outcomes)
    if factor_id is None and pa_id is not None:
        factor_id = pa_id
    elif factor_id is None and sel.order is not None:
        factor_id = 900_000 + market_id * 10 + sel.order
    elif factor_id is None:
        factor_id = abs(hash(sel.it)) % 2_000_000_000

    label = sel.name or sel.odds_frac or str(factor_id)
    return {
        "factor_id": factor_id,
        "odds": sel.odds_decimal,
        "line_param": market_id,
        "line_param_text": sel.odds_frac or label,
        "selection_name": sel.name,
        "is_handicap_total": bool(sel.fields.get("HA")),
    }


def _outcomes_from_selections(
    selections: list[SelectionState],
    *,
    market_id: int,
    market_name: str | None,
) -> list[dict[str, Any]]:
    standard = _use_standard_factors(market_id, market_name, selections)
    n_outcomes = len([s for s in selections if s.odds_decimal is not None])
    rows: list[dict[str, Any]] = []
    for sel in selections:
        row = _selection_outcome_dict(
            sel,
            market_id=market_id,
            market_name=market_name,
            standard_factors=standard,
            n_outcomes=n_outcomes,
        )
        if row:
            rows.append(row)
    return rows


def _legacy_outcomes(selections: list[SelectionState]) -> tuple[OddsOutcome, ...]:
    outcomes: list[OddsOutcome] = []
    for sel in selections:
        if sel.odds_decimal is None or sel.order is None:
            continue
        factor_id = OUTCOME_FACTOR_BY_OR.get(sel.order)
        if factor_id is None:
            continue
        outcomes.append(
            OddsOutcome(
                factor_id=factor_id,
                odds=sel.odds_decimal,
                line_param_text=sel.odds_frac,
            )
        )
    return tuple(outcomes)


def map_state_to_changes(
    state: ZapFeedState,
    *,
    version: int | None = None,
    live_only: bool = False,
) -> list[Change]:
    packet_version = version if version is not None else state.frame_count
    changes: list[Change] = []

    for event in state.export_events(live_only=live_only):
        ref = _event_ref(event, state)
        sport_name = state.sport_name(event)

        changes.append(
            Change(
                change_type=ChangeType.FIXTURE,
                match_payload_id=event.fi,
                packet_version=packet_version,
                payload={
                    "sport_payload_id": ref.sport_payload_id,
                    "sport_name": sport_name,
                    "league_payload_id": ref.league_payload_id,
                    "league_name": event.competition,
                    "country_name": event.competition,
                    "team1": ref.team1,
                    "team2": ref.team2,
                    "place": ref.place,
                    "competition": event.competition,
                    "name": event.name,
                    "live": event.live,
                },
            )
        )

        if event.score or event.minute is not None or event.timer_secs is not None:
            score1, score2 = (
                _parse_score(event.score) if event.score else (None, None)
            )
            timer = _timer_payload(event)
            changes.append(
                Change(
                    change_type=ChangeType.SCORE,
                    match_payload_id=event.fi,
                    packet_version=packet_version,
                    payload={
                        "score1": score1,
                        "score2": score2,
                        "score": event.score,
                        **timer,
                    },
                )
            )

        if import_all_from_socket():
            markets = state.markets_with_odds(event)
        else:
            selections = state.main_market_outcomes(event)
            if len(_legacy_outcomes(selections)) >= 2:
                markets = [(main_market_id(), main_market_name(), selections)]
            else:
                markets = []

        open_outcomes = 0
        for market_id, market_name, selections in markets:
            outcomes = _outcomes_from_selections(
                selections,
                market_id=market_id,
                market_name=market_name,
            )
            if len(outcomes) < 1:
                continue
            open_outcomes += len(outcomes)
            display_market = market_name or f"Market {market_id}"
            changes.append(
                Change(
                    change_type=ChangeType.ODDS,
                    match_payload_id=event.fi,
                    packet_version=packet_version,
                    payload={
                        "market_event_id": event.fi,
                        "market_event_name": display_market,
                        "market_id": market_id,
                        "outcomes": outcomes,
                    },
                )
            )

        changes.append(
            Change(
                change_type=ChangeType.BETTING_STATUS,
                match_payload_id=event.fi,
                packet_version=packet_version,
                payload={
                    "state": "unblocked" if open_outcomes >= 1 else "blocked",
                },
            )
        )

    return changes


def state_summary(state: ZapFeedState) -> PacketSummary:
    events = state.export_events(live_only=False)
    if import_all_from_socket():
        odds_markets = sum(len(state.markets_with_odds(e)) for e in events)
        outcome_total = sum(
            len(sels)
            for e in events
            for _mid, _name, sels in state.markets_with_odds(e)
        )
        sports = len({e.sport_class for e in events if e.sport_class is not None})
    else:
        odds_markets = sum(
            1 for event in events if len(state.main_market_outcomes(event)) >= 2
        )
        outcome_total = sum(len(state.main_market_outcomes(event)) for event in events)
        sports = 1

    return PacketSummary(
        packet_version=state.frame_count,
        from_version=None,
        is_snapshot=True,
        sports=max(sports, 1),
        leagues=len({e.competition for e in events if e.competition}),
        fixtures=len(events),
        score_changes=sum(1 for e in events if e.score),
        betting_status_changes=len(events),
        odds_markets=odds_markets,
        odds_outcomes=outcome_total,
    )


def format_match_line(state: ZapFeedState, event: EventState) -> str:
    markets = state.markets_with_odds(event)
    primary = next(
        (m for m in markets if is_primary_market(m[1]) or m[0] == main_market_id()),
        markets[0] if markets else None,
    )
    if primary:
        _mid, mname, sels = primary
        parts = []
        for sel in sels[:3]:
            label = sel.name or str(sel.order)
            if sel.odds_frac:
                parts.append(f"{label}={sel.odds_frac}")
        odds_text = " ".join(parts) if parts else "—"
    else:
        odds_text = "—"

    score = event.score or "—"
    minute = f"{event.minute}'" if event.minute is not None else ""
    live = " LIVE" if event.live else ""
    name = event.name or f"FI {event.fi}"
    sport = state.sport_name(event)
    comp = event.competition or "?"
    return f"{name} [{score}{(' ' + minute) if minute else ''}] {odds_text}  ({sport} · {comp}){live}"


def print_odds_snapshot(state: ZapFeedState, *, live_only: bool = False) -> int:
    events = state.export_events(live_only=live_only)
    if not events:
        print("No match events with odds parsed yet.")
        return 0
    mode = "all sports / markets" if import_all_from_socket() else f"Soccer 1X2 ({main_market_name()})"
    print(f"Bet365 ({mode}): {len(events)} event(s)\n")
    for event in events[:80]:
        print(format_match_line(state, event))
    if len(events) > 80:
        print(f"\n… and {len(events) - 80} more")
    return len(events)


def replay_frame_summaries(summaries: list[dict[str, Any]]) -> ZapFeedState:
    """Rebuild state from listen -o JSON (preview-only — partial data)."""
    state = ZapFeedState()
    for item in summaries:
        preview = item.get("preview") or ""
        if preview.startswith(("F|", "U|", "I|", "D|")):
            state.apply_body(preview)
    return state
