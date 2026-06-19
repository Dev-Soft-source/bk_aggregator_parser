"""Tests for Playwright cookie header builder."""

from __future__ import annotations

import unittest

from ligastavok.browser_session import build_cookie_header


class BuildCookieHeaderTests(unittest.TestCase):
    def test_orders_qrator_first(self) -> None:
        cookies = [
            {"name": "_ga", "value": "1", "domain": ".ligastavok.ru"},
            {"name": "qrator_jsid2", "value": "abc", "domain": ".ligastavok.ru"},
            {"name": "cfidsgib-w-ligastavok", "value": "xyz", "domain": ".ligastavok.ru"},
        ]
        header = build_cookie_header(cookies)
        self.assertTrue(header.startswith("qrator_jsid2=abc"))
        self.assertIn("cfidsgib-w-ligastavok=xyz", header)
        self.assertIn("_ga=1", header)

    def test_ignores_other_domains(self) -> None:
        cookies = [
            {"name": "qrator_jsid2", "value": "abc", "domain": ".ligastavok.ru"},
            {"name": "other", "value": "nope", "domain": ".example.com"},
        ]
        header = build_cookie_header(cookies)
        self.assertEqual(header, "qrator_jsid2=abc")

    def test_navigate_live_reloads_same_url(self) -> None:
        from unittest.mock import MagicMock

        from ligastavok.browser_session import PlaywrightCookieSession

        page = MagicMock()
        page.url = "https://www.ligastavok.ru"
        session = PlaywrightCookieSession.__new__(PlaywrightCookieSession)
        session._navigate_live(
            page,
            "https://www.ligastavok.ru",
            5000,
        )
        page.reload.assert_called_once()
        page.goto.assert_not_called()

    def test_navigate_live_goto_different_url(self) -> None:
        from unittest.mock import MagicMock

        from ligastavok.browser_session import PlaywrightCookieSession

        page = MagicMock()
        page.url = "https://www.ligastavok.ru/personal"
        session = PlaywrightCookieSession.__new__(PlaywrightCookieSession)
        session._navigate_live(
            page,
            "https://www.ligastavok.ru",
            5000,
        )
        page.goto.assert_called_once()
        page.reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
