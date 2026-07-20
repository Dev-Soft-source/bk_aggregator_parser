"""Line-specific ZAP event selection (prematch on #/AO/, no live finished heuristics)."""

from __future__ import annotations

from bet365.odds_config import skip_esoccer
from bet365.state import EventState, ZapFeedState


def prematch_events_with_odds(state: ZapFeedState) -> list[EventState]:
    """
    Prematch fixtures that have priced odds.

    Unlike shared export_events(), does not treat prematch rows with SS/TM
    as finished — that logic is for live #/HO/ and drops many line rows.
    """
    result: list[EventState] = []
    for event in state.events.values():
        if event.live:
            continue
        if not state._is_match_event(event):
            continue
        if skip_esoccer() and state._is_esoccer(event):
            continue
        if not state._event_has_odds(event):
            continue
        result.append(event)
    result.sort(
        key=lambda e: (
            e.sport_class or 0,
            e.competition or "",
            e.name or "",
        )
    )
    return result
