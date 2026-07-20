"""Tests for bet365_line hub URL helpers."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bet365.cloudflare_gate import is_live_hub_url
from bet365_line.hub import (
    DEFAULT_FOOTBALL_URL,
    DEFAULT_SPORT_CLASS_IDS,
    is_football_line_url,
    is_line_hub_url,
    is_sport_list_url,
    sport_class_ids_from_env,
    sport_list_url,
)


class LineHubTests(unittest.TestCase):
    def test_ao_and_as_are_line_hubs(self) -> None:
        self.assertTrue(is_line_hub_url("https://www.bet365.com/#/AO/"))
        self.assertTrue(is_line_hub_url("https://www.bet365.com/#/AS/B1/K%5E5/"))
        self.assertTrue(is_line_hub_url("https://www.bet365.com/#/AS/B13/"))
        self.assertFalse(is_line_hub_url("https://www.bet365.com/#/HO/"))

    def test_sport_list_url_any_class(self) -> None:
        self.assertTrue(is_sport_list_url("https://www.bet365.com/#/AS/B1/"))
        self.assertTrue(is_sport_list_url("https://www.bet365.com/#/AS/B18/"))
        self.assertFalse(is_sport_list_url("https://www.bet365.com/#/AO/"))

    def test_football_line_url(self) -> None:
        self.assertTrue(is_football_line_url("https://www.bet365.com/#/AS/B1/"))
        self.assertFalse(is_football_line_url("https://www.bet365.com/#/AS/B13/"))

    def test_sport_list_url_builder(self) -> None:
        self.assertEqual(sport_list_url(13), "https://www.bet365.com/#/AS/B13/")

    def test_shared_gate_recognizes_as(self) -> None:
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/AS/B1/"))

    def test_default_football_url(self) -> None:
        self.assertIn("#/AS/B1", DEFAULT_FOOTBALL_URL)

    def test_default_sport_ids_include_football_and_tennis(self) -> None:
        self.assertIn(1, DEFAULT_SPORT_CLASS_IDS)
        self.assertIn(13, DEFAULT_SPORT_CLASS_IDS)
        self.assertIn(18, DEFAULT_SPORT_CLASS_IDS)

    def test_sport_ids_from_env(self) -> None:
        with patch.dict(os.environ, {"BET365_LINE_SPORT_IDS": "1,13,18"}, clear=False):
            self.assertEqual(sport_class_ids_from_env(), (1, 13, 18))


if __name__ == "__main__":
    unittest.main()
