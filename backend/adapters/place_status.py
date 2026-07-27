"""Shared place and betting-status meanings for all adapters (Track A).

Adapter-specific lifecycle helpers (e.g. fonbet.lifecycle) may extend these
constants but must not redefine the string meanings below.
"""

from __future__ import annotations

# --- Place ---

PLACE_LIVE = "live"
PLACE_LINE = "line"
PLACE_NOT_ACTIVE = "notActive"  # finished / left live book (Fonbet-compatible)

ACTIVE_LIVE_PLACES: frozenset[str] = frozenset({PLACE_LIVE})
PREMATCH_PLACES: frozenset[str] = frozenset({PLACE_LINE})
FINISHED_PLACES: frozenset[str] = frozenset({PLACE_NOT_ACTIVE})

# Places that typically belong in a live feed snapshot before prune.
LIVE_FEED_PLACES: frozenset[str] = frozenset({PLACE_LIVE, PLACE_NOT_ACTIVE})

# --- Betting status ---

STATUS_UNBLOCKED = "unblocked"
STATUS_BLOCKED = "blocked"
STATUS_PARTIAL = "partial"

KNOWN_BETTING_STATES: frozenset[str] = frozenset(
    {STATUS_UNBLOCKED, STATUS_BLOCKED, STATUS_PARTIAL}
)

NON_BETTABLE_STATES: frozenset[str] = frozenset(
    {STATUS_BLOCKED, "unknown", "cancelled", "postponed"}
)


def normalize_place(raw: str | None) -> str:
    return (raw or "unknown").strip() or "unknown"


def normalize_betting_state(raw: str | None) -> str:
    if not raw:
        return STATUS_UNBLOCKED
    return raw.strip().lower() or STATUS_UNBLOCKED


def is_active_live(place: str | None) -> bool:
    return normalize_place(place) in ACTIVE_LIVE_PLACES


def is_prematch(place: str | None) -> bool:
    return normalize_place(place) in PREMATCH_PLACES


def is_finished_place(place: str | None) -> bool:
    return normalize_place(place) in FINISHED_PLACES


def is_bettable_state(state: str | None) -> bool:
    return normalize_betting_state(state) not in NON_BETTABLE_STATES
