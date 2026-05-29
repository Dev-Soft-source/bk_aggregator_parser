"""Two-odds scope: main match result — Home (1) and Away (2), not Draw (X)."""

from __future__ import annotations

import os

# Main match-winner markets: WIN2 = 2-way, WIN = 1X2 (we take _1 and _2 only).
DEFAULT_MARKET_TYPES: tuple[str, ...] = ("WIN2", "WIN")
DEFAULT_MARKET_TYPE = "WIN2"
DEFAULT_OUTCOME_KEYS: tuple[str, ...] = ("_1", "_2")

OUTCOME_LABELS: dict[str, str] = {
    "_1": "1",
    "x": "X",
    "_2": "2",
}


def main_market_type() -> str:
    """First market type when only one is configured via legacy env."""
    return main_market_types()[0]


def main_market_types() -> tuple[str, ...]:
    raw = os.getenv("LIGASTAVOK_MAIN_MARKET_TYPES", "").strip()
    if raw:
        return tuple(t.strip() for t in raw.split(",") if t.strip())
    legacy = os.getenv("LIGASTAVOK_MAIN_MARKET_TYPE", DEFAULT_MARKET_TYPE).strip()
    if legacy and legacy != DEFAULT_MARKET_TYPE:
        return (legacy,)
    return DEFAULT_MARKET_TYPES


def ordered_outcome_keys() -> tuple[str, ...]:
    raw = os.getenv("LIGASTAVOK_OUTCOME_KEYS", "_1,_2")
    keys = tuple(k.strip() for k in raw.split(",") if k.strip())
    if len(keys) != 2:
        raise ValueError(
            f"LIGASTAVOK_OUTCOME_KEYS must list exactly 2 outcome keys, got {raw!r}"
        )
    return keys


def outcome_key_is_allowed(outcome_key: str) -> bool:
    return outcome_key in ordered_outcome_keys()


def outcome_label(outcome_key: str) -> str:
    return OUTCOME_LABELS.get(outcome_key, outcome_key)
