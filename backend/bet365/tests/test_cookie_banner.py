"""Tests for bet365 cookie consent banner helpers."""

from __future__ import annotations

import unittest

from bet365.browser_session import _COOKIE_ACCEPT_LABELS
from bet365.config import DEFAULT_COOKIE_BANNER_DELAY_SECONDS, Bet365Config


class CookieBannerConfigTests(unittest.TestCase):
    def test_default_delay_is_five_seconds(self) -> None:
        self.assertEqual(DEFAULT_COOKIE_BANNER_DELAY_SECONDS, 5.0)

    def test_estonian_accept_all_label_present(self) -> None:
        self.assertIn("Nõustu kõigiga", _COOKIE_ACCEPT_LABELS)
        self.assertEqual(_COOKIE_ACCEPT_LABELS[0], "Nõustu kõigiga")

    def test_config_cookie_banner_defaults(self) -> None:
        cfg = Bet365Config.from_env()
        self.assertTrue(cfg.cookie_banner_auto_click)
        self.assertEqual(cfg.cookie_banner_auto_click_delay_seconds, 5.0)


if __name__ == "__main__":
    unittest.main()
