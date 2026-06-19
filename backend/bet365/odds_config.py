"""Bet365 market / outcome configuration."""

from __future__ import annotations

import os

# Fulltime Result (1X2) on bet365 soccer in-play feed.
DEFAULT_MARKET_ID = 1777
DEFAULT_MARKET_NAME = "Fulltime Result"

# Map bet365 PA OR slot → shared factor ids (Fonbet/Liga convention).
OUTCOME_FACTOR_BY_OR: dict[int, int] = {
    0: 921,  # home / 1
    1: 922,  # draw / X
    2: 923,  # away / 2
}

OUTCOME_LABEL_BY_OR: dict[int, str] = {
    0: "1",
    1: "X",
    2: "2",
}

# Primary win-market names (map to 921/922/923 for frontend).
PRIMARY_MARKET_NAMES: frozenset[str] = frozenset(
    {
        "Fulltime Result",
        "Match Winner",
        "Money Line",
        "To Win",
        "Match Result",
        "Winner",
    }
)


def import_all_from_socket() -> bool:
    raw = os.getenv("BET365_IMPORT_ALL", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def main_market_id() -> int:
    raw = os.getenv("BET365_MAIN_MARKET_ID", str(DEFAULT_MARKET_ID)).strip()
    return int(raw)


def main_market_name() -> str:
    return os.getenv("BET365_MAIN_MARKET_NAME", DEFAULT_MARKET_NAME).strip()


def soccer_class_id() -> int:
    return int(os.getenv("BET365_SOCCER_CLASS_ID", "1"))


def skip_esoccer() -> bool:
    return os.getenv("BET365_SKIP_ESOCCER", "true").lower() in ("1", "true", "yes", "on")


def is_primary_market(name: str | None) -> bool:
    if not name:
        return False
    return name.strip() in PRIMARY_MARKET_NAMES
