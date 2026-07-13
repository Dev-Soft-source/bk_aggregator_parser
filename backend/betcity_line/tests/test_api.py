"""URL / ntime helpers for Betcity line HTTP poll."""

from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from betcity_line.api import packet_ntime
from betcity_line.config import BetcityLineConfig


class BetcityLineApiTests(unittest.TestCase):
    def test_snapshot_url_has_no_md(self) -> None:
        cfg = BetcityLineConfig(
            base_url="https://ad.betcity.ru/d/off/events",
            rev="6",
            ver="82",
            csn="ooca9s",
            add="dep_events",
            poll_interval=10.0,
            timeout=30.0,
            connect_timeout=10.0,
        )
        url = cfg.snapshot_url()
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs.get("rev"), ["6"])
        self.assertEqual(qs.get("ver"), ["82"])
        self.assertEqual(qs.get("csn"), ["ooca9s"])
        self.assertEqual(qs.get("add"), ["dep_events"])
        self.assertNotIn("md", qs)

    def test_delta_url_includes_md(self) -> None:
        cfg = BetcityLineConfig(
            base_url="https://ad.betcity.ru/d/off/events",
            rev="6",
            ver="82",
            csn="ooca9s",
            add="dep_events",
            poll_interval=10.0,
            timeout=30.0,
            connect_timeout=10.0,
        )
        url = cfg.delta_url(1234567890)
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs.get("md"), ["1234567890"])

    def test_packet_ntime_from_reply(self) -> None:
        self.assertEqual(packet_ntime({"reply": {"ntime": 42}}), 42)
        self.assertEqual(packet_ntime({"ntime": 7}), 7)
        self.assertIsNone(packet_ntime({"reply": {}}))


if __name__ == "__main__":
    unittest.main()
