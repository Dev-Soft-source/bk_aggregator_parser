"""Mapper tests for 1xBet Get1x2_VZip."""

from __future__ import annotations

import unittest

from adapters.base import ChangeType
from lxbet_line.mapper import map_packet_to_changes


SAMPLE_PACKET = {
    "Id": 0,
    "Success": True,
    "Value": [
        {
            "I": 1001,
            "O1": "Home FC",
            "O2": "Away FC",
            "SI": 1,
            "SN": "Football",
            "LI": 10,
            "L": "Test League",
            "CN": "Testland",
            "S": 1780000000,
            "U": 1780000100,
            "E": [
                {"G": 1, "T": 1, "C": 2.1},
                {"G": 1, "T": 2, "C": 3.4},
                {"G": 1, "T": 3, "C": 3.2},
                {"G": 17, "T": 9, "C": 1.9, "P": 2.5},
            ],
            "SC": {
                "S": "62 minutes",
                "TS": 3745,
                "FS": {"S1": 1, "S2": 0},
            },
        },
        {
            "I": 1002,
            "O1": "Two Way A",
            "O2": "Two Way B",
            "SI": 4,
            "SN": "Tennis",
            "LI": 20,
            "L": "ATP",
            "S": 1780000200,
            "E": [
                {"G": 1, "T": 1, "C": 1.5},
                {"G": 1, "T": 3, "C": 2.5},
            ],
        },
        {
            "I": 1003,
            "O1": "No Away Odds",
            "SI": 1,
            "SN": "Football",
            "LI": 11,
            "L": "X",
            "E": [{"G": 1, "T": 1, "C": 1.2}],
        },
        {
            "I": 1004,
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
                {"G": 17, "T": 9, "C": 1.9, "P": 220.5},
            ],
        },
        {
            "I": 1005,
            "O1": "Heat",
            "O2": "Nets",
            "SI": 3,
            "SN": "Basketball",
            "LI": 31,
            "L": "NBA",
            "E": [
                {"G": 2766, "T": 3653, "C": 1.7},
                {"G": 2766, "T": 3654, "C": 15.0},
                {"G": 2766, "T": 3655, "C": 2.2},
            ],
        },
    ],
}


class LxbetLineMapperTests(unittest.TestCase):
    def test_1x2_maps_to_921_922_923_place_line(self) -> None:
        changes = map_packet_to_changes(SAMPLE_PACKET, version=1)
        fixtures = [c for c in changes if c.change_type == ChangeType.FIXTURE]
        # 1003 incomplete; 1001/1002 football/tennis; 1004/1005 basketball.
        self.assertEqual(len(fixtures), 4)
        self.assertEqual(
            {c.match_payload_id for c in fixtures}, {1001, 1002, 1004, 1005}
        )
        for fix in fixtures:
            self.assertEqual(fix.payload.get("place"), "line")

        odds = [c for c in changes if c.change_type == ChangeType.ODDS]
        by_id = {c.match_payload_id: c for c in odds}
        self.assertIn(1001, by_id)
        self.assertIn(1002, by_id)
        self.assertIn(1004, by_id)
        self.assertIn(1005, by_id)
        self.assertNotIn(1003, by_id)
        self.assertFalse(
            any(c.match_payload_id == 1003 for c in changes),
            "events without main odds must not be persisted",
        )

        outcomes = by_id[1001].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in outcomes], [921, 922, 923])
        self.assertEqual(outcomes[0]["odds"], 2.1)
        self.assertEqual(outcomes[1]["odds"], 3.4)
        self.assertEqual(outcomes[2]["odds"], 3.2)

        tennis = by_id[1002].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in tennis], [921, 923])

        bball_2way = by_id[1004].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in bball_2way], [921, 923])
        self.assertEqual(bball_2way[0]["odds"], 1.8)
        self.assertEqual(bball_2way[1]["odds"], 2.1)

        bball_1x2 = by_id[1005].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in bball_1x2], [921, 922, 923])
        self.assertEqual(bball_1x2[1]["odds"], 15.0)

    def test_score_and_timer(self) -> None:
        changes = map_packet_to_changes(SAMPLE_PACKET, version=1)
        score = next(
            c
            for c in changes
            if c.change_type == ChangeType.SCORE and c.match_payload_id == 1001
        )
        self.assertEqual(score.payload["score1"], 1)
        self.assertEqual(score.payload["score2"], 0)
        self.assertEqual(score.payload["timer_display"], "62 minutes")
        self.assertEqual(score.payload["timer_seconds"], 3745)


if __name__ == "__main__":
    unittest.main()
