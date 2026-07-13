"""Main match result odds: Home (1), Draw (X), Away (2)."""

from __future__ import annotations

import os

# Fonbet main 1X2: 921 = 1 (home), 922 = X (draw), 923 = 2 (away).
DEFAULT_FACTOR_IDS: tuple[int, ...] = (921, 922, 923)

OUTCOME_LABELS: dict[int, str] = {
    921: "1",
    922: "X",
    923: "2",
}


def ordered_factor_ids() -> tuple[int, ...]:
    """Factor ids in display order (2-way or full 1X2)."""
    raw = os.getenv("FONBET_ODDS_FACTOR_IDS", "921,922,923")
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    if len(ids) not in (2, 3):
        raise ValueError(
            f"FONBET_ODDS_FACTOR_IDS must list 2 or 3 factor ids, got {raw!r}"
        )
    return tuple(ids)


def allowed_factor_ids() -> frozenset[int]:
    return frozenset(ordered_factor_ids())


def factor_is_allowed(factor_id: int) -> bool:
    return factor_id in allowed_factor_ids()


def outcome_label(factor_id: int) -> str:
    return OUTCOME_LABELS.get(factor_id, str(factor_id))


def sort_outcomes_by_config(outcomes: list) -> list:
    """Order outcomes to match FONBET_ODDS_FACTOR_IDS (not numeric factor_id sort)."""
    order = {fid: i for i, fid in enumerate(ordered_factor_ids())}
    return sorted(outcomes, key=lambda o: order.get(o.factor_id, 99))
