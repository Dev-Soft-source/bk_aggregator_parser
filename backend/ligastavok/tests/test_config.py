"""Tests for browser refresh interval config."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ligastavok.config import _parse_browser_refresh


class BrowserRefreshConfigTests(unittest.TestCase):
    def test_default_range_9_15(self) -> None:
        with patch.dict(
            os.environ,
            {"LIGASTAVOK_BROWSER_REFRESH_RANGE": "", "LIGASTAVOK_BROWSER_REFRESH_EVERY": ""},
            clear=False,
        ):
            lo, hi, every = _parse_browser_refresh()
        self.assertEqual(lo, 15)
        self.assertEqual(hi, 25)
        self.assertEqual(every, 12)

    def test_custom_range(self) -> None:
        env = {
            "LIGASTAVOK_BROWSER_REFRESH_RANGE": "10-14",
            "LIGASTAVOK_BROWSER_REFRESH_EVERY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            lo, hi, _ = _parse_browser_refresh()
        self.assertEqual(lo, 10)
        self.assertEqual(hi, 14)

    def test_fixed_every_overrides(self) -> None:
        env = {
            "LIGASTAVOK_BROWSER_REFRESH_EVERY": "12",
            "LIGASTAVOK_BROWSER_REFRESH_RANGE": "9-15",
        }
        with patch.dict(os.environ, env, clear=False):
            lo, hi, every = _parse_browser_refresh()
        self.assertIsNone(lo)
        self.assertIsNone(hi)
        self.assertEqual(every, 12)


    def test_roll_refresh_in_range(self) -> None:
        import random
        from ligastavok.adapter import LigastavokAdapter
        from ligastavok.config import LigastavokApiConfig

        cfg = LigastavokApiConfig.from_env()
        cfg = LigastavokApiConfig(
            **{**cfg.__dict__, "browser_refresh_min": 15, "browser_refresh_max": 25}
        )
        adapter = LigastavokAdapter(cfg)
        random.seed(0)
        for _ in range(20):
            n = adapter._roll_refresh_interval()
            self.assertGreaterEqual(n, 15)
            self.assertLessEqual(n, 25)


if __name__ == "__main__":
    unittest.main()
