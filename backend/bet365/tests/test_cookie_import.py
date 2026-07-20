"""Tests for bet365 cookie import helpers."""

from __future__ import annotations

import unittest

from bet365.browser_session import _bet365_cookies_for_import


class CookieImportTests(unittest.TestCase):
    def test_filters_bet365_domains(self) -> None:
        raw = [
            {"name": "pstk", "value": "abc", "domain": ".bet365.com", "path": "/"},
            {"name": "other", "value": "x", "domain": ".google.com", "path": "/"},
        ]
        out = _bet365_cookies_for_import(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "pstk")

    def test_sets_default_path(self) -> None:
        raw = [{"name": "pstk", "value": "abc", "domain": "www.bet365.com"}]
        out = _bet365_cookies_for_import(raw)
        self.assertEqual(out[0]["path"], "/")

    def test_strips_unsupported_keys(self) -> None:
        raw = [
            {
                "name": "pstk",
                "value": "abc",
                "domain": ".bet365.com",
                "path": "/",
                "size": 99,
                "session": True,
            }
        ]
        out = _bet365_cookies_for_import(raw)
        self.assertNotIn("size", out[0])
        self.assertNotIn("session", out[0])


if __name__ == "__main__":
    unittest.main()
