"""Betcity market / outcome configuration (1X2 main line)."""

from __future__ import annotations

import os

# Main win market id in live `reply.main` frames (name often "Исход" / match result).
DEFAULT_MAIN_MARKET_ID = 69
DEFAULT_MAIN_BLOCK = "Wm"

# Map Betcity outcome keys → shared factor ids (Fonbet/Liga convention).
OUTCOME_FACTOR_BY_KEY: dict[str, int] = {
    "P1": 921,  # home / 1
    "X": 922,  # draw / X
    "P2": 923,  # away / 2
}

DEFAULT_FACTOR_IDS: tuple[int, ...] = (921, 922, 923)


def ordered_factor_ids() -> tuple[int, ...]:
    raw = os.getenv("BETCITY_ODDS_FACTOR_IDS", "921,922,923")
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    if len(ids) not in (2, 3):
        raise ValueError(
            f"BETCITY_ODDS_FACTOR_IDS must list 2 or 3 factor ids, got {raw!r}"
        )
    return tuple(ids)


def allowed_factor_ids() -> frozenset[int]:
    return frozenset(ordered_factor_ids())


def main_market_id() -> int:
    return int(os.getenv("BETCITY_MAIN_MARKET_ID", str(DEFAULT_MAIN_MARKET_ID)))


def main_block_key() -> str:
    return os.getenv("BETCITY_MAIN_BLOCK", DEFAULT_MAIN_BLOCK).strip() or DEFAULT_MAIN_BLOCK


def factor_for_outcome_key(key: str) -> int | None:
    return OUTCOME_FACTOR_BY_KEY.get(key)
