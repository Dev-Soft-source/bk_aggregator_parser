"""URL helpers for 1xBet line HTTP poll."""

from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from lxbet_line.api import merge_packets, packet_version
from lxbet_line.config import LxbetLineConfig


def _cfg(**overrides: object) -> LxbetLineConfig:
    base = dict(
        events_url="https://1xlite-55157.pro/service-api/LineFeed/Get1x2_VZip",
        sports_url="https://1xlite-55157.pro/service-api/LineFeed/GetSportsShortZip",
        champs_url="https://1xlite-55157.pro/service-api/LineFeed/GetChampsZip",
        sport_count="50",
        top_count="10",
        lng="en",
        mode="4",
        country="179",
        virtual_sports="true",
        fetch_all_sports=True,
        fetch_top=True,
        max_workers=1,
        skip_sport_ids=frozenset(),
        only_sport_ids=frozenset(),
        prune_coverage_min=0.9,
        prune_past_hours=48,
        poll_interval=20.0,
        timeout=60.0,
        request_pause_seconds=0.5,
    )
    base.update(overrides)
    return LxbetLineConfig(**base)  # type: ignore[arg-type]


class LxbetLineApiTests(unittest.TestCase):
    def test_sport_events_url(self) -> None:
        cfg = _cfg()
        url = cfg.sport_events_url(1)
        self.assertIn("/LineFeed/Get1x2_VZip", url)
        self.assertTrue(urlparse(url).query.startswith("sports=1"))
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs.get("sports"), ["1"])
        self.assertEqual(qs.get("count"), ["50"])

    def test_champ_events_url(self) -> None:
        cfg = _cfg()
        url = cfg.champ_events_url(123)
        self.assertTrue(urlparse(url).query.startswith("champs=123"))

    def test_top_url(self) -> None:
        cfg = _cfg()
        top = cfg.top_url()
        self.assertTrue(urlparse(top).query.startswith("count="))
        qs = parse_qs(urlparse(top).query)
        self.assertEqual(qs.get("count"), ["10"])
        self.assertEqual(qs.get("top"), ["true"])

    def test_merge_packets_by_event_id(self) -> None:
        merged = merge_packets(
            {"Value": [{"I": 1, "O1": "A"}, {"I": 2, "O1": "B"}]},
            {"Value": [{"I": 2, "O1": "B2"}, {"I": 3, "O1": "C"}]},
        )
        by_id = {int(e["I"]): e["O1"] for e in merged["Value"]}
        self.assertEqual(by_id, {1: "A", 2: "B2", 3: "C"})

    def test_packet_version_uses_max_u(self) -> None:
        packet = {
            "Id": 0,
            "Value": [
                {"I": 1, "U": 100},
                {"I": 2, "U": 250},
                {"I": 3, "U": 200},
            ],
        }
        self.assertEqual(packet_version(packet), 250)


if __name__ == "__main__":
    unittest.main()
