"""Tests for browser refresh interval config."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ligastavok_live.config import _parse_browser_refresh


class BrowserRefreshConfigTests(unittest.TestCase):
    def test_default_range_9_15(self) -> None:
        with patch.dict(
            os.environ,
            {"LIGASTAVOK_BROWSER_REFRESH_RANGE": "", "LIGASTAVOK_BROWSER_REFRESH_EVERY": ""},
            clear=False,
        ):
            lo, hi, every = _parse_browser_refresh()
        self.assertEqual(lo, 12)
        self.assertEqual(hi, 16)
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


class LiveBrowserUrlTests(unittest.TestCase):
    def test_normalize_rejects_site_root(self) -> None:
        from ligastavok_live.config import LIVE_BROWSER_URL, _normalize_live_browser_url

        self.assertEqual(
            _normalize_live_browser_url("https://www.ligastavok.ru"),
            LIVE_BROWSER_URL,
        )
        self.assertEqual(
            _normalize_live_browser_url("https://www.ligastavok.ru/"),
            LIVE_BROWSER_URL,
        )

    def test_normalize_keeps_live_path(self) -> None:
        from ligastavok_live.config import _normalize_live_browser_url

        self.assertEqual(
            _normalize_live_browser_url("https://www.ligastavok.ru/live"),
            "https://www.ligastavok.ru/live",
        )
        self.assertEqual(
            _normalize_live_browser_url("https://www.ligastavok.ru/live/"),
            "https://www.ligastavok.ru/live",
        )

    def test_from_env_pins_live_when_root_configured(self) -> None:
        from ligastavok_live.config import LIVE_BROWSER_URL, LigastavokApiConfig

        env = {
            "LIGASTAVOK_NS": "live",
            "LIGASTAVOK_BROWSER_URL": "https://www.ligastavok.ru",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = LigastavokApiConfig.from_env()
        self.assertEqual(cfg.browser_url, LIVE_BROWSER_URL)

    def test_live_referer(self) -> None:
        from ligastavok_live.config import live_config_from_env

        with patch.dict(
            os.environ,
            {"LIGASTAVOK_BROWSER_URL": "https://www.ligastavok.ru"},
            clear=False,
        ):
            cfg = live_config_from_env()
        self.assertEqual(cfg.browser_url, "https://www.ligastavok.ru/live")
        self.assertEqual(
            cfg.request_headers()["Referer"],
            "https://www.ligastavok.ru/live",
        )


class AdapterRefreshTests(unittest.TestCase):
    def test_roll_refresh_in_range(self) -> None:
        import random
        from ligastavok_live.adapter import LigastavokAdapter
        from ligastavok_live.config import LigastavokApiConfig

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
