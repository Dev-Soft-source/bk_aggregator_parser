"""Map Bet365 ZAP state to adapter changes with place=line (prematch only)."""

from __future__ import annotations

from adapters.base import Change, ChangeType, PacketSummary
from bet365.mapper import map_state_to_changes as _map_live
from bet365.mapper import state_summary as _state_summary
from bet365.odds_config import import_all_from_socket
from bet365.state import ZapFeedState
from bet365_line.state_export import prematch_events_with_odds


def map_state_to_changes(
    state: ZapFeedState,
    *,
    version: int | None = None,
) -> list[Change]:
    """
    Export prematch events from #/AO/ as place=line.

    Live / in-play rows (FS=1) are dropped — those belong to bet365 live (#/HO/).
    Score / betting_status changes are omitted for line.
    """
    prematch = prematch_events_with_odds(state)
    prematch_ids = {event.fi for event in prematch}
    if not prematch_ids:
        return []

    changes = _map_live(
        state,
        version=version,
        live_only=False,
        force_place="line",
    )
    out: list[Change] = []
    for change in changes:
        if change.match_payload_id not in prematch_ids:
            continue
        if change.change_type in (ChangeType.SCORE, ChangeType.BETTING_STATUS):
            continue
        out.append(change)
    return out


def state_summary(state: ZapFeedState) -> PacketSummary:
    """Summary counting prematch fixtures only (ignore live bleed from #/HO/)."""
    events = prematch_events_with_odds(state)
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
        sports = 1 if events else 0

    base = _state_summary(state)
    return PacketSummary(
        packet_version=base.packet_version,
        from_version=None,
        is_snapshot=True,
        sports=max(sports, 0),
        leagues=len({e.competition for e in events if e.competition}),
        fixtures=len(events),
        score_changes=0,
        betting_status_changes=0,
        odds_markets=odds_markets,
        odds_outcomes=outcome_total,
    )
