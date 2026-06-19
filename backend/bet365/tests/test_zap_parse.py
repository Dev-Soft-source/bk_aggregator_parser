"""Tests for bet365 ZAP parsing and odds mapping."""

from __future__ import annotations

import unittest
from pathlib import Path

from bet365.mapper import map_state_to_changes, print_odds_snapshot
from bet365.state import ZapFeedState
from bet365.zap_parse import (
    fractional_to_decimal,
    parse_fields,
    parse_match_teams,
    sport_class_from_event_fields,
)


SAMPLE_BODY = Path(__file__).resolve().parents[1] / "sample_soccer_body.txt"


class ZapParseTests(unittest.TestCase):
    def test_fractional_to_decimal(self) -> None:
        self.assertAlmostEqual(fractional_to_decimal("5/1"), 6.0)
        self.assertAlmostEqual(fractional_to_decimal("8/13"), 1.6153846, places=5)
        self.assertAlmostEqual(fractional_to_decimal("1/1"), 2.0)

    def test_parse_match_teams(self) -> None:
        self.assertEqual(parse_match_teams("PSG v Arsenal"), ("PSG", "Arsenal"))

    def test_sport_class_from_id_and_it(self) -> None:
        fields = parse_fields(
            "EV;FI=194475137;ID=194475137C78A_1_3;IT=L78-1-5-25704703_1_3;NA=A v B;"
        )
        self.assertEqual(sport_class_from_event_fields(fields), 78)
        fields_cl = parse_fields("EV;FI=1;CL=18;ID=194975679C18A_1_3;")
        self.assertEqual(sport_class_from_event_fields(fields_cl), 18)

    def test_parse_fields(self) -> None:
        fields = parse_fields("PA;FI=195412801;OD=5/1;OR=0;")
        self.assertEqual(fields["FI"], "195412801")
        self.assertEqual(fields["OD"], "5/1")


class ZapStateTests(unittest.TestCase):
    def test_sample_resolves_handball_not_unknown(self) -> None:
        if not SAMPLE_BODY.is_file():
            self.skipTest("sample_soccer_body.txt missing")
        state = ZapFeedState()
        state.apply_body(SAMPLE_BODY.read_text(encoding="utf-8"))
        hollabrunn = next(
            (e for e in state.events.values() if e.name and "Hollabrunn" in e.name),
            None,
        )
        self.assertIsNotNone(hollabrunn)
        assert hollabrunn is not None
        self.assertEqual(state.sport_class_for(hollabrunn), 78)
        self.assertEqual(state.sport_name(hollabrunn), "Handball")

    def test_load_sample_soccer_body(self) -> None:
        if not SAMPLE_BODY.is_file():
            self.skipTest("sample_soccer_body.txt missing")
        body = SAMPLE_BODY.read_text(encoding="utf-8")
        state = ZapFeedState()
        state.apply_body(body)
        self.assertGreater(len(state.events), 5)
        self.assertGreater(len(state.selections), 10)
        psg = next((e for e in state.events.values() if e.name and "PSG" in e.name), None)
        self.assertIsNotNone(psg)
        assert psg is not None
        outcomes = state.main_market_outcomes(psg)
        self.assertEqual(len(outcomes), 3)
        by_or = {s.order: s.odds_frac for s in outcomes}
        self.assertEqual(by_or[0], "5/1")
        self.assertEqual(by_or[1], "5/2")
        self.assertEqual(by_or[2], "8/13")

    def test_map_to_changes(self) -> None:
        if not SAMPLE_BODY.is_file():
            self.skipTest("sample_soccer_body.txt missing")
        state = ZapFeedState()
        state.apply_body(SAMPLE_BODY.read_text(encoding="utf-8"))
        changes = map_state_to_changes(state)
        odds = [c for c in changes if c.change_type.value == "odds"]
        self.assertGreater(len(odds), 5)

    def test_tennis_two_way_maps_to_921_923(self) -> None:
        state = ZapFeedState()
        state.sport_classes[13] = "Tennis"
        state.apply_body(
            "F|EV;FI=200;CL=13;NA=Player A v Player B;FS=1;OI=300;|"
            "MA;FI=300;ID=1763;NA=Match Winner;|"
            "PA;FI=300;ID=10;IT=L300-10_1;NA=Player A;OD=10/11;OR=0;|"
            "PA;FI=300;ID=11;IT=L300-11_1;NA=Player B;OD=10/11;OR=1;|"
        )
        changes = map_state_to_changes(state)
        odds = next(c for c in changes if c.change_type.value == "odds")
        factors = sorted(o["factor_id"] for o in odds.payload["outcomes"])
        self.assertEqual(factors, [921, 923])

    def test_import_all_multi_sport(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.sport_classes[2] = "Basketball"
        state.apply_body(
            "F|EV;FI=100;CL=2;NA=Lakers v Celtics;CT=NBA;FS=1;OI=200;|"
            "MA;FI=200;ID=1763;NA=Match Winner;|"
            "PA;FI=200;ID=10;IT=L200-10_1;NA=Lakers;OD=10/11;OR=0;|"
            "PA;FI=200;ID=11;IT=L200-11_1;NA=Celtics;OD=10/11;OR=1;|"
        )
        changes = map_state_to_changes(state)
        fixtures = [c for c in changes if c.change_type.value == "fixture"]
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].payload["sport_name"], "Basketball")
        odds = [c for c in changes if c.change_type.value == "odds"]
        self.assertEqual(len(odds), 1)
        self.assertEqual(len(odds[0].payload["outcomes"]), 2)

    def test_delta_update_by_path(self) -> None:
        state = ZapFeedState()
        state.apply_body(
            "F|EV;FI=999;CL=1;NA=Home v Away;FS=1;OI=888;|"
            "MA;FI=888;ID=1777;IT=L999-1777_1_3;NA=Fulltime Result;|"
            "PA;FI=888;ID=1;IT=L888-1_1_3;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=888;ID=2;IT=L888-2_1_3;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=888;ID=3;IT=L888-3_1_3;NA=Away;OD=4/1;OR=2;|"
        )
        chunk = "\x15L888-1_1_3\x01U|OD=9/4;|"
        state.apply_chunk(chunk)
        sel = state.selections["L888-1_1_3"]
        self.assertEqual(sel.odds_frac, "9/4")
        self.assertAlmostEqual(sel.odds_decimal or 0, 3.25)


if __name__ == "__main__":
    unittest.main()
