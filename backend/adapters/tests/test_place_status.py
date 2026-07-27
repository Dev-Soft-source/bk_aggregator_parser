"""Tests for shared place/status contract."""

from __future__ import annotations

import unittest

from adapters.place_status import (
    PLACE_LINE,
    PLACE_LIVE,
    PLACE_NOT_ACTIVE,
    STATUS_BLOCKED,
    STATUS_UNBLOCKED,
    is_active_live,
    is_bettable_state,
    is_finished_place,
    is_prematch,
    normalize_betting_state,
    normalize_place,
)


class PlaceStatusTests(unittest.TestCase):
    def test_normalize_place(self) -> None:
        self.assertEqual(normalize_place("live"), PLACE_LIVE)
        self.assertEqual(normalize_place(None), "unknown")
        self.assertEqual(normalize_place("  "), "unknown")

    def test_place_flags(self) -> None:
        self.assertTrue(is_active_live(PLACE_LIVE))
        self.assertFalse(is_active_live(PLACE_LINE))
        self.assertTrue(is_prematch(PLACE_LINE))
        self.assertTrue(is_finished_place(PLACE_NOT_ACTIVE))

    def test_betting_state(self) -> None:
        self.assertEqual(normalize_betting_state(None), STATUS_UNBLOCKED)
        self.assertEqual(normalize_betting_state("Blocked"), STATUS_BLOCKED)
        self.assertTrue(is_bettable_state(STATUS_UNBLOCKED))
        self.assertFalse(is_bettable_state(STATUS_BLOCKED))
        self.assertFalse(is_bettable_state("cancelled"))


if __name__ == "__main__":
    unittest.main()
