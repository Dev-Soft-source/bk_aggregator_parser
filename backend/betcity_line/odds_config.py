"""Betcity line market / outcome configuration (2-way main line)."""

from __future__ import annotations

# Re-use live factor mapping (921/923) so frontend columns stay consistent.
from betcity_live.odds_config import (  # noqa: F401
    OUTCOME_FACTOR_BY_KEY,
    allowed_factor_ids,
    factor_for_outcome_key,
    main_block_key,
    main_market_id,
    ordered_factor_ids,
)
