"""Fonbet event lifecycle helpers (Track B2).

Place/status string meanings come from the shared Track A contract
(`adapters.place_status`). Fonbet keeps feed-specific helpers here.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.place_status import (
    ACTIVE_LIVE_PLACES,
    FINISHED_PLACES,
    LIVE_FEED_PLACES,
    NON_BETTABLE_STATES,
    PLACE_LINE,
    PLACE_LIVE,
    PLACE_NOT_ACTIVE,
    PREMATCH_PLACES,
    is_active_live,
    is_bettable_state,
    is_finished_place,
    normalize_betting_state,
    normalize_place,
)

# Re-export shared constants for existing fonbet imports.
__all__ = [
    "ACTIVE_LIVE_PLACES",
    "FINISHED_PLACES",
    "LIVE_FEED_PLACES",
    "NON_BETTABLE_STATES",
    "PLACE_LINE",
    "PLACE_LIVE",
    "PLACE_NOT_ACTIVE",
    "PREMATCH_PLACES",
    "active_live_match_ids",
    "classify_fixture_lifecycle",
    "collect_soft_finished_match_ids",
    "event_will_be_live",
    "is_active_live",
    "is_bettable_state",
    "is_clock_stopped",
    "is_esports_context",
    "is_finished_place",
    "is_live_feed_place",
    "is_prematch_place",
    "is_soft_finished_live",
    "normalize_betting_state",
    "normalize_fonbet_betting_state",
    "normalize_place",
    "parse_timer_minutes",
    "should_keep_last_odds",
    "should_persist_fixture",
]

_TIMER_MMSS = re.compile(r"^(\d{1,3}):(\d{2})$")
_TIMER_MINUTE = re.compile(r"^(\d+)(?:\+(\d+))?'?$")
_ESPORT_HINT = re.compile(
    r"esport|e-?soccer|fc\s*24|fc24|cyber|esportsbattle|virtual",
    re.IGNORECASE,
)
_MATCH_LEN_HINT = re.compile(r"(\d+)\s*min", re.IGNORECASE)


def is_live_feed_place(place: str | None) -> bool:
    return normalize_place(place) in LIVE_FEED_PLACES


def is_prematch_place(place: str | None) -> bool:
    return normalize_place(place) in PREMATCH_PLACES


def event_will_be_live(event: dict[str, Any] | None) -> bool:
    """Fonbet marks upcoming live-board lingerers with state.willBeLive."""
    if not event:
        return False
    state = event.get("state")
    if isinstance(state, dict) and state.get("willBeLive") is True:
        return True
    return bool(event.get("willBeLive"))


def should_keep_last_odds(odds_value: Any) -> bool:
    """Fonbet uses v=0 (or missing) for suspended selections — retain prior price."""
    try:
        return float(odds_value) > 0
    except (TypeError, ValueError):
        return False


def normalize_fonbet_betting_state(raw: str | None) -> str:
    """Map Fonbet eventBlocks / lifecycle labels onto shared statuses."""
    state = normalize_betting_state(raw)
    if state in {"cancelled", "canceled"}:
        return "cancelled"
    if state == "postponed":
        return "postponed"
    return state


def parse_timer_minutes(
    timer_display: str | None = None,
    timer_seconds: Any = None,
) -> float | None:
    """Return elapsed match minutes from Fonbet timer fields."""
    if timer_seconds is not None:
        try:
            return float(timer_seconds) / 60.0
        except (TypeError, ValueError):
            pass
    text = (timer_display or "").strip()
    if not text:
        return None
    mmss = _TIMER_MMSS.match(text)
    if mmss:
        return int(mmss.group(1)) + int(mmss.group(2)) / 60.0
    minute = _TIMER_MINUTE.match(text)
    if minute:
        base = int(minute.group(1))
        extra = int(minute.group(2) or 0)
        return float(base + extra)
    return None


def is_clock_stopped(timer_direction: Any) -> bool:
    """Fonbet timerDirection: 0 = frozen, 1 = counting up."""
    try:
        return int(timer_direction) == 0
    except (TypeError, ValueError):
        return False


def is_esports_context(
    *,
    sport_name: str | None = None,
    league_name: str | None = None,
    team1: str | None = None,
    team2: str | None = None,
) -> bool:
    blob = " ".join(
        part for part in (sport_name, league_name, team1, team2) if part
    )
    return bool(_ESPORT_HINT.search(blob))


def infer_esports_match_length(league_name: str | None) -> int:
    if league_name:
        match = _MATCH_LEN_HINT.search(league_name)
        if match:
            return int(match.group(1))
        if "esportsbattle" in league_name.lower():
            return 6
    return 6


def is_football_context(
    *,
    score_function: str | None = None,
    sport_name: str | None = None,
) -> bool:
    sf = (score_function or "").strip().lower()
    if sf == "football":
        return True
    sport = (sport_name or "").strip().lower()
    return sport in {"football", "soccer"}


def is_soft_finished_live(
    *,
    place: str | None,
    betting_state: str | None = None,
    timer_display: str | None = None,
    timer_seconds: Any = None,
    timer_direction: Any = None,
    score_function: str | None = None,
    has_positive_odds: bool | None = None,
    sport_name: str | None = None,
    league_name: str | None = None,
    team1: str | None = None,
    team2: str | None = None,
) -> bool:
    """
    True when Fonbet still sends place=live but the match has left the in-play book.

    Mirrors Bet365 soft-finish rules adapted to Fonbet timers:
    - Football at >=90' with frozen clock and blocked (or no prices)
    - Football past regulation with no positive main odds
    - Short esports (FC 24 / EsportsBattle) at match length with frozen clock
    """
    if normalize_place(place) != PLACE_LIVE:
        return False

    minutes = parse_timer_minutes(timer_display, timer_seconds)
    if minutes is None:
        return False

    stopped = is_clock_stopped(timer_direction)
    state = normalize_fonbet_betting_state(betting_state)
    blocked = state in {"blocked", "cancelled", "postponed"}
    no_odds = has_positive_odds is False

    if is_esports_context(
        sport_name=sport_name,
        league_name=league_name,
        team1=team1,
        team2=team2,
    ):
        match_len = infer_esports_match_length(league_name)
        if minutes + 1e-9 < match_len:
            return False
        # Virtual matches end at ML; last odds often linger.
        return stopped or no_odds or blocked

    if is_football_context(score_function=score_function, sport_name=sport_name):
        if minutes + 1e-9 < 90:
            return False
        if stopped and (blocked or no_odds):
            return True
        if no_odds:
            return True
        return False

    return False


def classify_fixture_lifecycle(
    place: str | None,
    betting_state: str | None = None,
    *,
    will_be_live: bool | None = None,
) -> dict[str, Any]:
    """
    Derive lifecycle flags for a fixture.

    Fonbet nuances:
    - ``notActive`` + ``willBeLive`` → upcoming / prematch linger on live feed (not finished)
    - ``notActive`` without ``willBeLive`` → left active live set (treat as finished for prune)
    - ``line`` → prematch; ``live`` → active in-play
    """
    place_n = normalize_place(place)
    upcoming = place_n == PLACE_NOT_ACTIVE and bool(will_be_live)
    finished = place_n in FINISHED_PLACES and not upcoming
    active_live = place_n in ACTIVE_LIVE_PLACES
    prematch = place_n in PREMATCH_PLACES or upcoming
    state = normalize_fonbet_betting_state(betting_state)

    if state in {"cancelled", "postponed"} or state in NON_BETTABLE_STATES:
        bettable = False
    else:
        bettable = (active_live or prematch) and is_bettable_state(state)

    return {
        "place": place_n,
        "finished": finished,
        "upcoming_live": upcoming,
        "active_live": active_live,
        "prematch": prematch,
        "bettable": bettable,
        "leave_live_set": not active_live,
        "prematch_to_live_pending": upcoming,
        "betting_state": state,
    }


def should_persist_fixture(
    place: str | None,
    *,
    will_be_live: bool | None = None,
    mode: str = "live",
) -> bool:
    """
    Whether a Fonbet level-1 event should be written for the current poll mode.

    Live poll: persist ``live`` only. Finished ``notActive`` is omitted so
    ``prune_absent_matches(place=live)`` drops the prior live row.
    Upcoming ``notActive``+willBeLive is omitted until it flips to ``live``
    (appears once when it joins the active set).
    Line poll (future): persist ``line``.
    """
    place_n = normalize_place(place)
    if mode == "live":
        return place_n == PLACE_LIVE
    if mode in {"prematch", "line"}:
        return place_n == PLACE_LINE
    life = classify_fixture_lifecycle(place_n, will_be_live=will_be_live)
    return bool(life["active_live"] or life["prematch"])


def active_live_match_ids(events: list[dict[str, Any]]) -> set[int]:
    """Root match ids that belong in the live prune keep-set."""
    ids: set[int] = set()
    for event in events:
        if event.get("level") != 1:
            continue
        if normalize_place(event.get("place")) != PLACE_LIVE:
            continue
        eid = event.get("id")
        if eid is not None:
            ids.add(int(eid))
    return ids


def collect_soft_finished_match_ids(
    *,
    events: list[dict[str, Any]],
    events_by_id: dict[int, dict[str, Any]],
    event_miscs: dict[int, dict[str, Any]],
    live_infos: dict[int, dict[str, Any]],
    event_blocks: dict[int, dict[str, Any]],
    custom_factors: list[dict[str, Any]],
    sports_by_id: dict[int, dict[str, Any]] | None = None,
    league_to_sport: dict[int, int] | None = None,
    known_match_ids: set[int] | None = None,
    resolve_match_id=None,
) -> set[int]:
    """
    Match ids that are still place=live in the feed but should leave the live DB set.
    """
    sports_by_id = sports_by_id or {}
    league_to_sport = league_to_sport or {}
    known = set(known_match_ids or ())

    positive_odds: dict[int, bool] = {}
    for entry in custom_factors:
        market_event_id = entry.get("e")
        if market_event_id is None:
            continue
        root_id = int(market_event_id)
        if resolve_match_id is not None:
            resolved = resolve_match_id(market_event_id, events_by_id, known)
            if resolved is not None:
                root_id = int(resolved)
        # Main-line presence: only root event factor rows.
        if int(market_event_id) != root_id:
            continue
        has_pos = any(
            should_keep_last_odds(factor.get("v"))
            for factor in entry.get("factors", [])
        )
        if has_pos:
            positive_odds[root_id] = True
        else:
            positive_odds.setdefault(root_id, False)

    candidates: set[int] = set()
    for event in events:
        if event.get("level") != 1:
            continue
        if normalize_place(event.get("place")) != PLACE_LIVE:
            continue
        candidates.add(int(event["id"]))

    for source in (event_miscs, live_infos, event_blocks):
        for eid in source:
            if resolve_match_id is not None:
                root = resolve_match_id(eid, events_by_id, known | candidates)
            elif int(eid) in known or int(eid) in candidates:
                root = int(eid)
            else:
                root = None
            if root is not None:
                candidates.add(int(root))

    finished: set[int] = set()
    for match_id in candidates:
        event = events_by_id.get(match_id, {})
        place = event.get("place", PLACE_LIVE) if event else PLACE_LIVE
        if event and normalize_place(place) not in {PLACE_LIVE, "unknown"}:
            continue

        misc = event_miscs.get(match_id, {})
        live = live_infos.get(match_id, {})
        timer_display = live.get("timer") or misc.get("timer")
        timer_seconds = live.get("timerSeconds", misc.get("timerSeconds"))
        timer_direction = live.get("timerDirection", misc.get("timerDirection"))
        score_function = live.get("scoreFunction") or misc.get("scoreFunction")
        betting_state = event_blocks.get(match_id, {}).get("state")

        league_id = event.get("sportId") if event else None
        sport_id = league_to_sport.get(league_id) if league_id else None
        league_name = (
            sports_by_id.get(league_id, {}).get("name") if league_id else None
        )
        sport_name = (
            sports_by_id.get(sport_id, {}).get("name") if sport_id else None
        )

        has_odds = positive_odds.get(match_id)  # True / False / None

        if is_soft_finished_live(
            place=place,
            betting_state=betting_state,
            timer_display=timer_display,
            timer_seconds=timer_seconds,
            timer_direction=timer_direction,
            score_function=score_function,
            has_positive_odds=has_odds,
            sport_name=sport_name,
            league_name=league_name,
            team1=event.get("team1") if event else None,
            team2=event.get("team2") if event else None,
        ):
            finished.add(match_id)

    return finished
