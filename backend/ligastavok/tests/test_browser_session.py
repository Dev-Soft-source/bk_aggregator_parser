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


if __name__ == "__main__":
    unittest.main()
