"""Tests for sport name resolution and display overrides."""

from __future__ import annotations

import unittest

from fonbet.sports_reference import display_name_en, resolve_name_en


class SportsReferenceTests(unittest.TestCase):
    def test_football_display_override(self) -> None:
        self.assertEqual(display_name_en(1, "Soccer"), "Football")
        self.assertEqual(display_name_en(2, "Basketball"), "Basketball")
        self.assertIsNone(display_name_en(None, None))

    def test_resolve_name_en_fonbet_football(self) -> None:
        ref_id, name_en = resolve_name_en(1, {1: "Soccer"})
        self.assertEqual(ref_id, 1)
        self.assertEqual(name_en, "Football")


if __name__ == "__main__":
    unittest.main()
