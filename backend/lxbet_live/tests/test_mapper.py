"""Mapper tests for 1xBet LiveFeed Get1x2_VZip."""

from __future__ import annotations

import unittest

from adapters.base import ChangeType
from lxbet_live.mapper import map_packet_to_changes


SAMPLE_PACKET = {
    "Id": 0,
    "Success": True,
    "Value": [
        {
            "I": 2001,
            "O1": "Home FC",
            "O2": "Away FC",
            "SI": 1,
            "SN": "Football",
            "LI": 10,
            "L": "Test League",
            "CN": "Testland",
            "S": 1780000000,
            "U": 1780000100,
            "R": 100,
            "E": [
                {"G": 1, "T": 1, "C": 2.1},
                {"G": 1, "T": 2, "C": 3.4},
                {"G": 1, "T": 3, "C": 3.2},
            ],
            "SC": {
                "SLS": "92 minutes",
                "CPS": "2nd half",
                "TS": 5544,
                "FS": {"S1": 1, "S2": 0},
            },
        },
        {
            "I": 2002,
            "O1": "Lakers",
            "O2": "Celtics",
            "SI": 3,
            "SN": "Basketball",
            "LI": 30,
            "L": "NBA",
            "S": 1780000300,
            "E": [
                {"G": 101, "T": 401, "C": 1.8},
                {"G": 101, "T": 402, "C": 2.1},
            ],
            "SC": {
                "SLS": "10 min remaining",
                "CPS": "3rd quarter",
                "TS": 600,
                "FS": {"S1": 49, "S2": 59},
            },
        },
        {
            "I": 2003,
            "O1": "No Odds Side",
            "SI": 1,
            "SN": "Football",
            "LI": 11,
            "L": "X",
            "E": [{"G": 1, "T": 1, "C": 1.2}],
        },
    ],
}


class LxbetLiveMapperTests(unittest.TestCase):
    def test_maps_place_live_and_main_odds(self) -> None:
        changes = map_packet_to_changes(SAMPLE_PACKET, version=1)
        fixtures = [c for c in changes if c.change_type == ChangeType.FIXTURE]
        self.assertEqual(len(fixtures), 2)
        self.assertEqual({c.match_payload_id for c in fixtures}, {2001, 2002})
        for fix in fixtures:
            self.assertEqual(fix.payload.get("place"), "live")

        odds = {c.match_payload_id: c for c in changes if c.change_type == ChangeType.ODDS}
        self.assertIn(2001, odds)
        self.assertIn(2002, odds)
        self.assertNotIn(2003, odds)

        football = odds[2001].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in football], [921, 922, 923])

        bball = odds[2002].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in bball], [921, 923])

    def test_live_timer_prefers_sls(self) -> None:
        changes = map_packet_to_changes(SAMPLE_PACKET, version=1)
        score = next(
            c
            for c in changes
            if c.change_type == ChangeType.SCORE and c.match_payload_id == 2001
        )
        self.assertEqual(score.payload["score1"], 1)
        self.assertEqual(score.payload["score2"], 0)
        self.assertEqual(score.payload["timer_display"], "92 minutes")
        self.assertEqual(score.payload["timer_seconds"], 5544)

        bball_score = next(
            c
            for c in changes
            if c.change_type == ChangeType.SCORE and c.match_payload_id == 2002
        )
        self.assertEqual(bball_score.payload["score1"], 49)
        self.assertEqual(bball_score.payload["score2"], 59)
        self.assertEqual(bball_score.payload["timer_display"], "10 min remaining")


if __name__ == "__main__":
    unittest.main()
