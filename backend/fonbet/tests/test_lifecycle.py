"""Fonbet lifecycle helpers and mapper regression (Track B2)."""

from __future__ import annotations

import unittest

from adapters.base import ChangeType
from fonbet.lifecycle import (
    active_live_match_ids,
    classify_fixture_lifecycle,
    event_will_be_live,
    should_keep_last_odds,
    should_persist_fixture,
)
from fonbet.mapper import discover_events, map_packet_to_changes
from fonbet.odds_config import ordered_factor_ids


def _sport_tree() -> list[dict]:
    return [
        {"id": 1, "kind": "sport", "name": "Football", "alias": "football"},
        {"id": 10, "kind": "segment", "name": "Test League", "parentId": 1},
    ]


class FonbetLifecycleHelperTests(unittest.TestCase):
    def test_keep_last_odds_skips_zero(self) -> None:
        self.assertTrue(should_keep_last_odds(1.85))
        self.assertFalse(should_keep_last_odds(0))
        self.assertFalse(should_keep_last_odds("0"))
        self.assertFalse(should_keep_last_odds(None))

    def test_will_be_live_flag(self) -> None:
        self.assertTrue(event_will_be_live({"state": {"willBeLive": True}}))
        self.assertFalse(event_will_be_live({"state": {"willBeLive": False}}))
        self.assertFalse(event_will_be_live({"place": "notActive"}))

    def test_finished_vs_upcoming_not_active(self) -> None:
        finished = classify_fixture_lifecycle("notActive", will_be_live=False)
        self.assertTrue(finished["finished"])
        self.assertTrue(finished["leave_live_set"])
        self.assertFalse(finished["bettable"])

        upcoming = classify_fixture_lifecycle("notActive", will_be_live=True)
        self.assertFalse(upcoming["finished"])
        self.assertTrue(upcoming["upcoming_live"])
        self.assertTrue(upcoming["prematch_to_live_pending"])
        self.assertTrue(upcoming["leave_live_set"])

    def test_live_and_line_flags(self) -> None:
        live = classify_fixture_lifecycle("live", "unblocked")
        self.assertTrue(live["active_live"])
        self.assertTrue(live["bettable"])
        self.assertFalse(live["leave_live_set"])

        line = classify_fixture_lifecycle("line", "unblocked")
        self.assertTrue(line["prematch"])
        self.assertTrue(line["bettable"])
        self.assertTrue(line["leave_live_set"])

    def test_cancelled_and_postponed_not_bettable(self) -> None:
        for state in ("cancelled", "canceled", "postponed", "blocked"):
            life = classify_fixture_lifecycle("live", state)
            self.assertFalse(life["bettable"], state)

    def test_persist_rules(self) -> None:
        self.assertTrue(should_persist_fixture("live", mode="live"))
        self.assertFalse(should_persist_fixture("notActive", mode="live"))
        self.assertFalse(
            should_persist_fixture("notActive", mode="live", will_be_live=True)
        )
        self.assertTrue(should_persist_fixture("line", mode="line"))
        self.assertFalse(should_persist_fixture("live", mode="line"))

    def test_active_live_match_ids(self) -> None:
        events = [
            {"id": 1, "level": 1, "place": "live"},
            {"id": 2, "level": 1, "place": "notActive", "state": {"willBeLive": True}},
            {"id": 3, "level": 1, "place": "notActive"},
            {"id": 4, "level": 2, "place": "live"},
            {"id": 5, "level": 1, "place": "line"},
        ]
        self.assertEqual(active_live_match_ids(events), {1})

    def test_football_ft_blocked_soft_finished(self) -> None:
        from fonbet.lifecycle import is_soft_finished_live

        self.assertTrue(
            is_soft_finished_live(
                place="live",
                betting_state="blocked",
                timer_display="90:00",
                timer_seconds=5400,
                timer_direction=0,
                score_function="Football",
                has_positive_odds=True,
                sport_name="Football",
            )
        )

    def test_football_ht_not_finished(self) -> None:
        from fonbet.lifecycle import is_soft_finished_live

        self.assertFalse(
            is_soft_finished_live(
                place="live",
                betting_state="blocked",
                timer_display="45:00",
                timer_seconds=2700,
                timer_direction=0,
                score_function="Football",
                has_positive_odds=True,
                sport_name="Football",
            )
        )

    def test_football_injury_time_with_odds_kept(self) -> None:
        from fonbet.lifecycle import is_soft_finished_live

        self.assertFalse(
            is_soft_finished_live(
                place="live",
                betting_state="unblocked",
                timer_display="92:10",
                timer_seconds=5530,
                timer_direction=1,
                score_function="Football",
                has_positive_odds=True,
                sport_name="Football",
            )
        )

    def test_football_past_regulation_no_odds_finished(self) -> None:
        from fonbet.lifecycle import is_soft_finished_live

        self.assertTrue(
            is_soft_finished_live(
                place="live",
                betting_state="unblocked",
                timer_display="103:28",
                timer_seconds=6208,
                timer_direction=1,
                score_function="Football",
                has_positive_odds=False,
                sport_name="Football",
            )
        )

    def test_esports_at_match_length_finished(self) -> None:
        from fonbet.lifecycle import is_soft_finished_live

        self.assertTrue(
            is_soft_finished_live(
                place="live",
                betting_state="unblocked",
                timer_display="6:00",
                timer_seconds=360,
                timer_direction=0,
                score_function="Football",
                has_positive_odds=True,
                sport_name="Esports",
                league_name="FC 24. EsportsBattle",
            )
        )


class FonbetSoftFinishMapperTests(unittest.TestCase):
    def test_mapper_skips_ft_blocked_football(self) -> None:
        packet = {
            "packetVersion": 1,
            "sports": _sport_tree(),
            "events": [
                {
                    "id": 9001,
                    "level": 1,
                    "sportId": 10,
                    "team1": "A",
                    "team2": "B",
                    "place": "live",
                }
            ],
            "eventBlocks": [{"eventId": 9001, "state": "blocked"}],
            "customFactors": [
                {
                    "e": 9001,
                    "factors": [
                        {"f": 921, "v": 1.5},
                        {"f": 922, "v": 3.5},
                        {"f": 923, "v": 6.0},
                    ],
                }
            ],
            "eventMiscs": [],
            "liveEventInfos": [
                {
                    "eventId": 9001,
                    "timer": "90:00",
                    "timerSeconds": 5400,
                    "timerDirection": 0,
                    "scoreFunction": "Football",
                    "score1": 2,
                    "score2": 1,
                }
            ],
        }
        changes = map_packet_to_changes(packet)
        self.assertEqual(
            [c for c in changes if c.change_type == ChangeType.FIXTURE],
            [],
        )
        self.assertEqual(
            [c for c in changes if c.change_type == ChangeType.ODDS],
            [],
        )


class FonbetLifecycleMapperTests(unittest.TestCase):
    def test_new_live_event_emitted_once(self) -> None:
        packet = {
            "packetVersion": 1,
            "sports": _sport_tree(),
            "events": [
                {
                    "id": 1001,
                    "level": 1,
                    "sportId": 10,
                    "team1": "A",
                    "team2": "B",
                    "place": "live",
                }
            ],
            "eventBlocks": [],
            "customFactors": [],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        changes = map_packet_to_changes(packet)
        fixtures = [c for c in changes if c.change_type == ChangeType.FIXTURE]
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].match_payload_id, 1001)

    def test_not_active_finished_not_emitted(self) -> None:
        packet = {
            "packetVersion": 1,
            "sports": _sport_tree(),
            "events": [
                {
                    "id": 1002,
                    "level": 1,
                    "sportId": 10,
                    "team1": "A",
                    "team2": "B",
                    "place": "notActive",
                }
            ],
            "eventBlocks": [],
            "customFactors": [],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        changes = map_packet_to_changes(packet)
        self.assertEqual(
            [c for c in changes if c.change_type == ChangeType.FIXTURE],
            [],
        )
        self.assertEqual(discover_events(packet, mode="live"), [])

    def test_prematch_line_discoverable(self) -> None:
        packet = {
            "packetVersion": 1,
            "sports": _sport_tree(),
            "events": [
                {
                    "id": 1003,
                    "level": 1,
                    "sportId": 10,
                    "team1": "A",
                    "team2": "B",
                    "place": "line",
                }
            ],
            "eventBlocks": [],
            "customFactors": [],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        events = discover_events(packet, mode="prematch")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].place, "line")
        self.assertEqual(discover_events(packet, mode="live"), [])

    def test_suspended_odds_omitted_keep_last(self) -> None:
        packet = {
            "packetVersion": 2,
            "fromVersion": 1,
            "sports": [],
            "events": [],
            "eventBlocks": [{"eventId": 2002, "state": "blocked"}],
            "customFactors": [
                {
                    "e": 2002,
                    "factors": [
                        {"f": 921, "v": 0},
                        {"f": 922, "v": 0},
                        {"f": 923, "v": 0},
                    ],
                }
            ],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        changes = map_packet_to_changes(packet, known_match_ids={2002})
        odds = [c for c in changes if c.change_type == ChangeType.ODDS]
        self.assertEqual(odds, [])
        # Status still emitted when block present via score-path / odds-only path.
        # Odds-only with empty outcomes: still need status from eventBlocks merge.
        # eventBlocks alone without events/scores may not emit — emit via known path:
        # re-map with a score tick style block on known match.
        packet2 = {
            "packetVersion": 3,
            "fromVersion": 2,
            "sports": [],
            "events": [],
            "eventBlocks": [{"eventId": 2002, "state": "blocked"}],
            "customFactors": [],
            "eventMiscs": [{"id": 2002, "score1": 1, "score2": 0}],
            "liveEventInfos": [],
        }
        changes2 = map_packet_to_changes(packet2, known_match_ids={2002})
        statuses = [
            c for c in changes2 if c.change_type == ChangeType.BETTING_STATUS
        ]
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].payload["state"], "blocked")

    def test_partial_suspend_keeps_positive_odds(self) -> None:
        packet = {
            "packetVersion": 2,
            "fromVersion": 1,
            "sports": [],
            "events": [],
            "eventBlocks": [],
            "customFactors": [
                {
                    "e": 2003,
                    "factors": [
                        {"f": 921, "v": 1.9},
                        {"f": 922, "v": 0},
                        {"f": 923, "v": 4.2},
                    ],
                }
            ],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        changes = map_packet_to_changes(packet, known_match_ids={2003})
        odds = next(c for c in changes if c.change_type == ChangeType.ODDS)
        values = {o["factor_id"]: o["odds"] for o in odds.payload["outcomes"]}
        self.assertEqual(values.get(921), 1.9)
        self.assertEqual(values.get(923), 4.2)
        self.assertNotIn(922, values)

    def test_cancelled_status_normalized(self) -> None:
        packet = {
            "packetVersion": 1,
            "sports": _sport_tree(),
            "events": [
                {
                    "id": 1004,
                    "level": 1,
                    "sportId": 10,
                    "team1": "A",
                    "team2": "B",
                    "place": "live",
                }
            ],
            "eventBlocks": [{"eventId": 1004, "state": "canceled"}],
            "customFactors": [],
            "eventMiscs": [],
            "liveEventInfos": [],
        }
        changes = map_packet_to_changes(packet)
        status = next(c for c in changes if c.change_type == ChangeType.BETTING_STATUS)
        self.assertEqual(status.payload["state"], "cancelled")
        life = classify_fixture_lifecycle("live", "cancelled")
        self.assertFalse(life["bettable"])


class FonbetMapperOddsBudgetTests(unittest.TestCase):
    def test_odds_at_most_configured_slots(self) -> None:
        # Align with FONBET_ODDS_FACTOR_IDS (2-way or full 1X2).
        from pathlib import Path
        import json

        path = Path(__file__).resolve().parents[1] / "test.json"
        if not path.is_file():
            self.skipTest("missing test.json")
        with path.open(encoding="utf-8") as handle:
            packet = json.load(handle)
        changes = map_packet_to_changes(packet)
        limit = len(ordered_factor_ids())
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
                limit,
                f"match {match_id} has {count} odds outcomes, expected <= {limit}",
            )


if __name__ == "__main__":
    unittest.main()
