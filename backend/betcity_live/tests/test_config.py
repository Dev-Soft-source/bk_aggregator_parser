"""Unit tests for Betcity WebSocket config parsing."""

from __future__ import annotations

import unittest
from dataclasses import replace

from betcity_live.config import (
    DEFAULT_WS_URL,
    BetcityConfig,
    chrome_proxy_server,
    normalize_proxy,
    requests_proxies,
)


class BetcityConfigTests(unittest.TestCase):
    def test_default_url_has_live_id_and_csn(self) -> None:
        cfg = BetcityConfig(
            ws_url=DEFAULT_WS_URL,
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie=None,
            user_agent="test",
            listen_seconds=30.0,
        )
        self.assertEqual(cfg.channel_id(), "live")
        self.assertEqual(cfg.csn(), "ooca9s")

    def test_custom_csn_from_url(self) -> None:
        cfg = BetcityConfig(
            ws_url="wss://sc.betcity.ru/?id=live&csn=abc123",
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie=None,
            user_agent="test",
            listen_seconds=10.0,
        )
        self.assertEqual(cfg.channel_id(), "live")
        self.assertEqual(cfg.csn(), "abc123")

    def test_ws_headers_include_cookie_when_set(self) -> None:
        cfg = BetcityConfig(
            ws_url=DEFAULT_WS_URL,
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie="session=xyz",
            user_agent="UA",
            listen_seconds=5.0,
        )
        headers = cfg.ws_headers()
        self.assertEqual(headers["Origin"], "https://betcity.ru")
        self.assertEqual(headers["Cookie"], "session=xyz")
        self.assertEqual(headers["User-Agent"], "UA")

    def test_ws_headers_omit_cookie_when_missing(self) -> None:
        cfg = BetcityConfig(
            ws_url=DEFAULT_WS_URL,
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie=None,
            user_agent="UA",
            listen_seconds=5.0,
        )
        self.assertNotIn("Cookie", cfg.ws_headers())

    def test_replace_url_override(self) -> None:
        cfg = BetcityConfig(
            ws_url=DEFAULT_WS_URL,
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie=None,
            user_agent="UA",
            listen_seconds=5.0,
        )
        updated = replace(cfg, ws_url="wss://sc.betcity.ru/?id=line&csn=zz")
        self.assertEqual(updated.channel_id(), "line")
        self.assertEqual(updated.csn(), "zz")

    def test_proxy_helpers(self) -> None:
        self.assertEqual(normalize_proxy("1.2.3.4:8080"), "http://1.2.3.4:8080")
        self.assertEqual(normalize_proxy("http://1.2.3.4:8080"), "http://1.2.3.4:8080")
        self.assertEqual(chrome_proxy_server("1.2.3.4:8080"), "1.2.3.4:8080")
        self.assertEqual(chrome_proxy_server("http://1.2.3.4:8080"), "1.2.3.4:8080")
        self.assertEqual(
            requests_proxies("1.2.3.4:8080"),
            {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"},
        )

    def test_browser_defaults(self) -> None:
        cfg = BetcityConfig(
            ws_url=DEFAULT_WS_URL,
            origin="https://betcity.ru",
            referer="https://betcity.ru/",
            cookie=None,
            user_agent="UA",
            listen_seconds=5.0,
        )
        self.assertFalse(cfg.use_browser)
        self.assertEqual(cfg.browser_cdp_url, "http://127.0.0.1:9224")
        self.assertIn("betcity.ru", cfg.browser_url)


if __name__ == "__main__":
    unittest.main()
