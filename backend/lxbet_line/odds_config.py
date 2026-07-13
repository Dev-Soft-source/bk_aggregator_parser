"""1xBet main market factor mapping."""

from __future__ import annotations

import os

# (group_id, outcome_type) → factor_id. Tried in order until home+away exist.
# G=1: classic 1X2 (Football, Tennis, …)
# G=2766: Basketball 1X2 (incl. rare draw)
# G=101: Basketball 2-way moneyline
MARKET_FACTOR_MAPS: tuple[tuple[int, dict[int, int]], ...] = (
    (1, {1: 921, 2: 922, 3: 923}),
    (2766, {3653: 921, 3654: 922, 3655: 923}),
    (101, {401: 921, 402: 923}),
)

DEFAULT_FACTOR_IDS: tuple[int, ...] = (921, 922, 923)
MAIN_GROUP_ID = 1


def ordered_factor_ids() -> tuple[int, ...]:
    raw = os.getenv("LXBET_ODDS_FACTOR_IDS", "921,922,923")
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    if len(ids) not in (2, 3):
        raise ValueError(
            f"LXBET_ODDS_FACTOR_IDS must list 2 or 3 factor ids, got {raw!r}"
        )
    return tuple(ids)


def allowed_factor_ids() -> frozenset[int]:
    return frozenset(ordered_factor_ids())


def market_factor_maps() -> tuple[tuple[int, dict[int, int]], ...]:
    """Return configured maps, optionally forcing classic group via env."""
    raw = os.getenv("LXBET_MAIN_GROUP_ID")
    if raw and raw.strip():
        group_id = int(raw)
        for gid, mapping in MARKET_FACTOR_MAPS:
            if gid == group_id:
                return ((gid, mapping),)
        # Unknown forced group: keep classic T=1/2/3 on that group.
        return ((group_id, {1: 921, 2: 922, 3: 923}),)
    return MARKET_FACTOR_MAPS


def main_group_id() -> int:
    """Primary market id used when writing odds_lines.market_id."""
    return int(os.getenv("LXBET_MAIN_GROUP_ID", str(MAIN_GROUP_ID)))
