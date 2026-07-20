"""Main match result odds — Home / Draw / Away (1X2) with Fonbet-compatible factor slots."""

from __future__ import annotations

import os

# Prefer 1X2 (WIN) so Draw is available; fall back to 2-way (WIN2).
DEFAULT_MARKET_TYPES: tuple[str, ...] = ("WIN", "WIN2")
DEFAULT_MARKET_TYPE = "WIN"
DEFAULT_OUTCOME_KEYS: tuple[str, ...] = ("_1", "x", "_2")

OUTCOME_LABELS: dict[str, str] = {
    "_1": "1",
    "x": "X",
    "_2": "2",
}

# Canonical Fonbet-style factor slots for the UI / odds_lines.factor_id (INTEGER).
# Liga Stavok facIds are huge BIGINT values — they go in line_param_raw.
DEFAULT_FACTOR_SLOTS_1X2: tuple[int, ...] = (921, 922, 923)
DEFAULT_FACTOR_SLOTS_2WAY: tuple[int, ...] = (921, 923)


def main_market_type() -> str:
    """First market type when only one is configured via legacy env."""
    return main_market_types()[0]


def main_market_types() -> tuple[str, ...]:
    raw = os.getenv("LIGASTAVOK_MAIN_MARKET_TYPES", "").strip()
    if raw:
        return tuple(t.strip() for t in raw.split(",") if t.strip())
    legacy = os.getenv("LIGASTAVOK_MAIN_MARKET_TYPE", "").strip()
    if legacy:
        rest = tuple(t for t in DEFAULT_MARKET_TYPES if t != legacy)
        return (legacy, *rest)
    return DEFAULT_MARKET_TYPES


def ordered_outcome_keys() -> tuple[str, ...]:
    raw = os.getenv("LIGASTAVOK_OUTCOME_KEYS", "_1,x,_2").strip()
    keys = tuple(k.strip() for k in raw.split(",") if k.strip())
    if len(keys) not in (2, 3):
        raise ValueError(
            f"LIGASTAVOK_OUTCOME_KEYS must list 2 or 3 outcome keys, got {raw!r}"
        )
    return keys


def factor_slots() -> tuple[int, ...]:
    keys = ordered_outcome_keys()
    raw = os.getenv("LIGASTAVOK_ODDS_FACTOR_IDS", "").strip() or os.getenv(
        "FONBET_ODDS_FACTOR_IDS", ""
    ).strip()
    if raw:
        ids = tuple(int(x.strip()) for x in raw.split(",") if x.strip())
        if len(keys) == 3:
            if len(ids) >= 3:
                return ids[:3]
            if len(ids) == 2:
                return (ids[0], 922, ids[1])
        if len(keys) == 2:
            if len(ids) >= 3:
                return (ids[0], ids[2])
            if len(ids) == 2:
                return ids
    return DEFAULT_FACTOR_SLOTS_1X2 if len(keys) == 3 else DEFAULT_FACTOR_SLOTS_2WAY


def outcome_key_is_allowed(outcome_key: str) -> bool:
    return outcome_key in ordered_outcome_keys()


def outcome_label(outcome_key: str) -> str:
    return OUTCOME_LABELS.get(outcome_key, outcome_key)
