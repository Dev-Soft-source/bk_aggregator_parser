"""Unit tests for Fonbet packet mapper."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from adapters.base import ChangeType
from fonbet.mapper import (
    discover_events,
    discover_sports,
    map_packet_to_changes,
    packet_summary,
)


FONBET_PKG = Path(__file__).resolve().parents[1]
TEST_JSON = FONBET_PKG / "test.json"


class FonbetMapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not TEST_JSON.is_file():
            raise unittest.SkipTest(f"Missing fixture: {TEST_JSON}")
        with TEST_JSON.open(encoding="utf-8") as handle:
            cls.packet = json.load(handle)

    def test_discover_sports_non_empty(self) -> None:
        sports = discover_sports(self.packet)
        self.assertGreater(len(sports), 0)
        self.assertTrue(all(s.payload_id for s in sports))

    def test_delta_packet_not_snapshot(self) -> None:
        summary = packet_summary(self.packet)
        self.assertFalse(summary.is_snapshot)
        self.assertGreater(summary.from_version or 0, 0)

    def test_map_produces_changes(self) -> None:
        changes = map_packet_to_changes(self.packet)
        types = {c.change_type for c in changes}
        self.assertIn(ChangeType.FIXTURE, types)
        self.assertTrue(
            ChangeType.SCORE in types or ChangeType.ODDS in types,
            "delta should include score or odds updates",
        )

    def test_discover_events_live_filter(self) -> None:
        events = discover_events(self.packet, mode="live")
        for event in events:
            self.assertIn(event.place, ("live", "notActive"))

    def test_packet_summary_counts(self) -> None:
        summary = packet_summary(self.packet)
        changes = map_packet_to_changes(self.packet)
        self.assertEqual(summary.fixtures, sum(1 for c in changes if c.change_type == ChangeType.FIXTURE))
        self.assertGreaterEqual(summary.odds_outcomes, 0)

    def test_odds_at_most_two_per_match(self) -> None:
        changes = map_packet_to_changes(self.packet)
        by_match: dict[int, int] = {}
        for change in changes:
            if change.change_type != ChangeType.ODDS:
                continue
            mid = change.match_payload_id
            n = len(change.payload.get("outcomes", []))
            by_match[mid] = by_match.get(mid, 0) + n
        for match_id, count in by_match.items():
            self.assertLessEqual(
                count,
                2,
                f"match {match_id} has {count} odds outcomes, expected <= 2",
            )


if __name__ == "__main__":
    unittest.main()
