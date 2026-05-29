"""Unit tests for Liga Stavok mapper and patch applier."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from adapters.base import ChangeType
from ligastavok.mapper import (
    discover_events,
    discover_sports,
    map_packet_to_changes,
    packet_summary,
)
from ligastavok.patch import apply_patch

PKG = Path(__file__).resolve().parents[1]
FIXTURE = PKG / "ligastavok.json"


class LigastavokMapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not FIXTURE.is_file():
            raise unittest.SkipTest(f"Missing fixture: {FIXTURE}")
        with FIXTURE.open(encoding="utf-8") as handle:
            cls.packet = json.load(handle)

    def test_discover_sports_non_empty(self) -> None:
        sports = discover_sports(self.packet)
        self.assertGreater(len(sports), 0)

    def test_snapshot_summary(self) -> None:
        summary = packet_summary(self.packet)
        self.assertTrue(summary.is_snapshot)
        self.assertGreater(summary.fixtures, 0)

    def test_map_produces_core_change_types(self) -> None:
        changes = map_packet_to_changes(self.packet)
        types = {c.change_type for c in changes}
        self.assertIn(ChangeType.FIXTURE, types)
        self.assertIn(ChangeType.ODDS, types)

    def test_discover_events_live_filter(self) -> None:
        events = discover_events(self.packet, mode="live")
        for event in events:
            self.assertEqual(event.place, "live")

    def test_odds_win_market_picks_home_and_away_only(self) -> None:
        item = {
            "id": 1,
            "gameId": 10,
            "ids": {"tournamentId": 20},
            "event": {"team1": "A", "team2": "B"},
            "markets": {
                "_568628544": {
                    "id": 568628544,
                    "title": "Победитель",
                    "type": "WIN",
                    "position": 1,
                    "locked": False,
                }
            },
            "outcomes": {
                "_3781896348": {
                    "outcomeKey": "_1",
                    "facId": 60010743284,
                    "value": 2.13,
                    "marketId": "_568628544",
                },
                "_3781896349": {
                    "outcomeKey": "x",
                    "facId": 60010743297,
                    "value": 5.1,
                    "marketId": "_568628544",
                },
                "_3781896350": {
                    "outcomeKey": "_2",
                    "facId": 60010743184,
                    "value": 2.13,
                    "marketId": "_568628544",
                },
            },
        }
        from ligastavok.mapper import _odds_outcomes

        outcomes = _odds_outcomes(item)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].factor_id, 60010743284)
        self.assertEqual(outcomes[0].odds, 2.13)
        self.assertEqual(outcomes[1].factor_id, 60010743184)
        self.assertEqual(outcomes[1].odds, 2.13)

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
            self.assertLessEqual(count, 2, f"match {match_id} has {count} outcomes")


class LigastavokPatchTests(unittest.TestCase):
    def test_apply_match_time_patch(self) -> None:
        doc = {"event": {"matchTime": "80"}, "outcomes": {}}
        patched = apply_patch(
            doc,
            [{"op": "replace", "path": "/event/matchTime", "value": "82"}],
        )
        self.assertEqual(patched["event"]["matchTime"], "82")

    def test_apply_outcome_value_patch(self) -> None:
        doc = {"outcomes": {"_1": {"value": 1.5, "facId": 100}}}
        patched = apply_patch(
            doc,
            [{"op": "replace", "path": "/outcomes/_1/value", "value": 1.55}],
        )
        self.assertEqual(patched["outcomes"]["_1"]["value"], 1.55)


if __name__ == "__main__":
    unittest.main()
