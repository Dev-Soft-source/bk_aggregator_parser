"""Tests for Playwright cookie header builder."""

from __future__ import annotations

import unittest

from ligastavok_line.browser_session import build_cookie_header


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

        from ligastavok_line.browser_session import PlaywrightCookieSession

        page = MagicMock()
        page.url = "https://www.ligastavok.ru/prematch"
        session = PlaywrightCookieSession.__new__(PlaywrightCookieSession)
        session._config = MagicMock(promo_auto_click=False)
        session._promo_dismissed = False
        session._navigate_live(
            page,
            "https://www.ligastavok.ru/prematch",
            5000,
        )
        page.reload.assert_called_once()
        page.goto.assert_not_called()

    def test_navigate_live_goto_different_url(self) -> None:
        from unittest.mock import MagicMock

        from ligastavok_line.browser_session import PlaywrightCookieSession

        page = MagicMock()
        page.url = "https://www.ligastavok.ru/live"
        session = PlaywrightCookieSession.__new__(PlaywrightCookieSession)
        session._config = MagicMock(promo_auto_click=False)
        session._promo_dismissed = False
        session._navigate_live(
            page,
            "https://www.ligastavok.ru/prematch",
            5000,
        )
        page.goto.assert_called_once()
        page.reload.assert_not_called()

    def test_click_promo_bonus_button(self) -> None:
        from unittest.mock import MagicMock

        from ligastavok_line.browser_session import PlaywrightCookieSession

        page = MagicMock()
        page.frames = []
        page.main_frame = page
        button = MagicMock()
        button.is_visible.return_value = True
        page.get_by_role.return_value = button

        session = PlaywrightCookieSession.__new__(PlaywrightCookieSession)
        session._config = MagicMock(
            promo_auto_click=True,
            promo_auto_click_delay_seconds=0,
        )
        session._promo_dismissed = False
        session._page = page

        self.assertTrue(session._maybe_dismiss_promo_dialog(page))
        button.click.assert_called()
        self.assertTrue(session._promo_dismissed)
        page.get_by_role.assert_any_call("button", name="Получить бонус")


if __name__ == "__main__":
    unittest.main()
