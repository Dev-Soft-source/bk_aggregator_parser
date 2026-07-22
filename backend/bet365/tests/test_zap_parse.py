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
        statuses = [c for c in changes if c.change_type.value == "betting_status"]
        self.assertGreater(len(statuses), 0)
        self.assertTrue(all(c.payload.get("state") in ("unblocked", "blocked") for c in statuses))
        self.assertTrue(any(c.payload.get("state") == "unblocked" for c in statuses))

    def test_finished_non_live_with_score_not_exported(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=701;CL=1;NA=Home v Away;CT=League;FS=0;SS=2-1;TM=90;OI=702;|"
            "MA;FI=702;ID=1777;NA=Fulltime Result;|"
            "PA;FI=702;ID=1;IT=L702-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=702;ID=2;IT=L702-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=702;ID=3;IT=L702-3_1;NA=Away;OD=4/1;OR=2;|"
        )
        self.assertTrue(state._is_finished(state.events[701]))
        self.assertEqual(state.export_events(), [])
        self.assertEqual(state.drop_finished_events(), 1)
        self.assertNotIn(701, state.events)

    def test_live_match_still_exported(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=801;CL=1;NA=Home v Away;CT=League;FS=1;SS=1-0;TM=22;OI=802;|"
            "MA;FI=802;ID=1777;NA=Fulltime Result;|"
            "PA;FI=802;ID=1;IT=L802-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=802;ID=2;IT=L802-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=802;ID=3;IT=L802-3_1;NA=Away;OD=4/1;OR=2;|"
        )
        exported = state.export_events()
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].fi, 801)
        self.assertEqual(state.drop_finished_events(), 0)

    def test_betting_status_blocked_when_suspended(self) -> None:
        import os
        from unittest.mock import patch

        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=101;CL=1;NA=Home v Away;CT=League;FS=1;OI=201;|"
            "MA;FI=201;ID=1777;NA=Fulltime Result;|"
            "PA;FI=201;ID=1;IT=L201-1_1;NA=Home;OD=2/1;OR=0;SU=1;|"
            "PA;FI=201;ID=2;IT=L201-2_1;NA=Draw;OD=3/1;OR=1;SU=1;|"
            "PA;FI=201;ID=3;IT=L201-3_1;NA=Away;OD=4/1;OR=2;SU=1;|"
        )
        with patch.dict(os.environ, {"BET365_IMPORT_ALL": "false"}):
            changes = map_state_to_changes(state)
        status = next(c for c in changes if c.change_type.value == "betting_status")
        self.assertEqual(status.payload["state"], "blocked")
        odds = next(c for c in changes if c.change_type.value == "odds")
        self.assertEqual(
            [o["factor_id"] for o in odds.payload["outcomes"]],
            [921, 922, 923],
        )

    def test_orphan_pa_without_ma_still_exports_1x2(self) -> None:
        """Esoccer mid-match deltas often send PA rows with OD but no MA parent."""
        import os
        from unittest.mock import patch

        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=198218415;CL=1;NA=Tunisia (Atlas) v Switzerland (Tiago);"
            "CT=Esoccer GT Leagues;FS=1;SS=0-2;TM=5;OI=198218415;ML=12;|"
            "PA;FI=198218415;ID=1;IT=L415-1;NA=Tunisia;OD=12/1;OR=0;SU=0;|"
            "PA;FI=198218415;ID=2;IT=L415-2;NA=Draw;OD=10/1;OR=1;SU=0;|"
            "PA;FI=198218415;ID=3;IT=L415-3;NA=Switzerland;OD=1/20;OR=2;SU=0;|"
        )
        with patch.dict(
            os.environ,
            {"BET365_IMPORT_ALL": "true", "BET365_SKIP_ESOCCER": "false"},
        ):
            changes = map_state_to_changes(state)
        status = next(c for c in changes if c.change_type.value == "betting_status")
        self.assertEqual(status.payload["state"], "unblocked")
        odds = next(c for c in changes if c.change_type.value == "odds")
        by_factor = {o["factor_id"]: o["odds"] for o in odds.payload["outcomes"]}
        self.assertEqual(by_factor[921], 13.0)
        self.assertEqual(by_factor[922], 11.0)
        self.assertAlmostEqual(by_factor[923], 1.05, places=2)

    def test_suspended_import_all_keeps_last_odds(self) -> None:
        import os
        from unittest.mock import patch

        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=101;CL=1;NA=Home v Away;CT=Esoccer GT;FS=1;OI=201;|"
            "MA;FI=201;ID=1777;NA=Fulltime Result;|"
            "PA;FI=201;ID=1;IT=L201-1_1;NA=Home;OD=12/1;OR=0;SU=1;|"
            "PA;FI=201;ID=2;IT=L201-2_1;NA=Draw;OD=10/1;OR=1;SU=1;|"
            "PA;FI=201;ID=3;IT=L201-3_1;NA=Away;OD=1/20;OR=2;SU=1;|"
        )
        with patch.dict(
            os.environ,
            {"BET365_IMPORT_ALL": "true", "BET365_SKIP_ESOCCER": "false"},
        ):
            changes = map_state_to_changes(state)
        status = next(c for c in changes if c.change_type.value == "betting_status")
        self.assertEqual(status.payload["state"], "blocked")
        odds = next(c for c in changes if c.change_type.value == "odds")
        self.assertEqual(len(odds.payload["outcomes"]), 3)

    def test_live_odds_removed_treated_finished(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=901;CL=1;NA=Home v Away;CT=League;FS=1;SS=3-0;TM=90;OI=902;|"
        )
        self.assertTrue(state._is_finished(state.events[901]))
        self.assertEqual(state.drop_finished_events(), 1)

    def test_soccer_90_clock_stopped_with_odds_stays_live(self) -> None:
        """FT linger / VAR pause at 90 with open odds — keep as live."""
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=911;CL=1;NA=Home v Away;CT=League;FS=1;SS=4-0;TM=90;TS=0;TT=0;ML=90;OI=912;|"
            "MA;FI=912;ID=1777;NA=Fulltime Result;|"
            "PA;FI=912;ID=1;IT=L912-1_1;NA=Home;OD=1/100;OR=0;|"
            "PA;FI=912;ID=2;IT=L912-2_1;NA=Draw;OD=50/1;OR=1;|"
            "PA;FI=912;ID=3;IT=L912-3_1;NA=Away;OD=100/1;OR=2;|"
        )
        self.assertFalse(state._is_finished(state.events[911]))
        self.assertEqual(len(state.export_events()), 1)
        self.assertEqual(state.drop_finished_events(), 0)

    def test_esoccer_at_match_length_finished_even_with_odds(self) -> None:
        """Short esoccer games linger at 8:00 with last prices — drop from live."""
        import os
        from unittest.mock import patch

        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=801;CL=1;NA=Home (A) v Away (B);"
            "CT=Esoccer H2H GG League - Joc de 8 minute;"
            "FS=1;SS=2-1;TM=8;TS=0;TT=0;ML=8;OI=802;|"
            "MA;FI=802;ID=1777;NA=Fulltime Result;|"
            "PA;FI=802;ID=1;IT=L802-1_1;NA=Home;OD=1/100;OR=0;|"
            "PA;FI=802;ID=2;IT=L802-2_1;NA=Draw;OD=50/1;OR=1;|"
            "PA;FI=802;ID=3;IT=L802-3_1;NA=Away;OD=100/1;OR=2;|"
        )
        with patch.dict(os.environ, {"BET365_SKIP_ESOCCER": "false"}):
            self.assertTrue(state._is_finished(state.events[801]))
            self.assertEqual(state.export_events(), [])
            self.assertEqual(state.drop_finished_events(), 1)

    def test_soccer_90_clock_stopped_no_odds_finished(self) -> None:
        """Past regulation, clock stopped, prices gone — drop from live."""
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=913;CL=1;NA=Home v Away;CT=League;FS=1;SS=4-0;TM=90;TS=0;TT=0;ML=90;OI=914;|"
        )
        self.assertTrue(state._is_finished(state.events[913]))
        self.assertEqual(state.export_events(), [])
        self.assertEqual(state.drop_finished_events(), 1)

    def test_soccer_90_stoppage_still_live(self) -> None:
        """Injury time: clock still ticking at 90+ — keep as live."""
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=921;CL=1;NA=Home v Away;CT=League;FS=1;SS=1-0;TM=90;TS=12;TT=1;ML=90;OI=922;|"
            "MA;FI=922;ID=1777;NA=Fulltime Result;|"
            "PA;FI=922;ID=1;IT=L922-1_1;NA=Home;OD=1/10;OR=0;|"
            "PA;FI=922;ID=2;IT=L922-2_1;NA=Draw;OD=10/1;OR=1;|"
            "PA;FI=922;ID=3;IT=L922-3_1;NA=Away;OD=20/1;OR=2;|"
        )
        self.assertFalse(state._is_finished(state.events[921]))
        self.assertEqual(len(state.export_events()), 1)
        self.assertEqual(state.drop_finished_events(), 0)

    def test_only_primary_market_uses_921_922_923(self) -> None:
        """HT / period markets must not overwrite Fulltime Result factors."""
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=931;CL=1;NA=Home v Away;CT=League;FS=1;SS=1-0;TM=70;OI=932;|"
            "MA;FI=932;ID=1777;NA=Fulltime Result;|"
            "PA;FI=932;ID=1;IT=L932-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=932;ID=2;IT=L932-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=932;ID=3;IT=L932-3_1;NA=Away;OD=4/1;OR=2;|"
            "MA;FI=932;ID=10161;NA=Rezultat la pauza;|"
            "PA;FI=932;ID=11;IT=L932-11_1;NA=Home;OD=10/1;OR=0;|"
            "PA;FI=932;ID=12;IT=L932-12_1;NA=Draw;OD=5/1;OR=1;|"
            "PA;FI=932;ID=13;IT=L932-13_1;NA=Away;OD=1/2;OR=2;|"
        )
        changes = map_state_to_changes(state)
        odds_changes = [c for c in changes if c.change_type.value == "odds"]
        factors_by_market: dict[int, list[int]] = {}
        for change in odds_changes:
            mid = int(change.payload.get("market_id") or 0)
            factors_by_market[mid] = [
                int(o["factor_id"]) for o in (change.payload.get("outcomes") or [])
            ]
        self.assertEqual(factors_by_market.get(1777), [921, 922, 923])
        self.assertNotEqual(factors_by_market.get(10161), [921, 922, 923])

    def test_tennis_match_winner_1763_maps_to_921_923(self) -> None:
        state = ZapFeedState()
        state.sport_classes[13] = "Tennis"
        state.apply_body(
            "F|EV;FI=941;CL=13;NA=Player A v Player B;FS=1;OI=942;|"
            "MA;FI=942;ID=1763;NA=Market 1763;|"
            "PA;FI=942;ID=10;IT=L942-10_1;NA=Player A;OD=10/11;OR=0;|"
            "PA;FI=942;ID=11;IT=L942-11_1;NA=Player B;OD=10/11;OR=1;|"
        )
        changes = map_state_to_changes(state)
        odds = next(c for c in changes if c.change_type.value == "odds")
        factors = sorted(o["factor_id"] for o in odds.payload["outcomes"])
        self.assertEqual(factors, [921, 923])

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

    def test_delete_event_cascades_markets_and_selections(self) -> None:
        state = ZapFeedState()
        state.apply_body(
            "F|EV;FI=999;CL=1;IT=L1-1-5-999_1_3;"
            "NA=Home v Away;FS=1;OI=888;|"
            "MA;FI=888;ID=1777;IT=L999-1777_1_3;NA=Fulltime Result;|"
            "PA;FI=888;ID=1;IT=L888-1_1_3;NA=Home;OD=2/1;OR=0;|"
        )

        state.apply_chunk("\x15L1-1-5-999_1_3\x01D|")

        self.assertNotIn(999, state.events)
        self.assertNotIn("L999-1777_1_3", state.markets)
        self.assertNotIn("L888-1_1_3", state.selections)

    def test_delete_market_cascades_cached_selections(self) -> None:
        state = ZapFeedState()
        state.apply_body(
            "F|EV;FI=999;CL=1;IT=L1-1-5-999_1_3;"
            "NA=Home v Away;FS=1;OI=888;|"
            "MA;FI=888;ID=1777;IT=L999-1777_1_3;NA=Fulltime Result;|"
            "PA;FI=888;ID=1;IT=L888-1_1_3;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=888;ID=2;IT=L888-2_1_3;NA=Away;OD=3/1;OR=1;|"
        )

        state.apply_body("D|", path="L999-1777_1_3")

        self.assertIn(999, state.events)
        self.assertNotIn("L999-1777_1_3", state.markets)
        self.assertNotIn("L888-1_1_3", state.selections)
        self.assertNotIn("L888-2_1_3", state.selections)
        self.assertEqual(state.export_events(), [])

    def test_delete_selection_accepts_ov_path(self) -> None:
        state = ZapFeedState()
        state.apply_body(
            "F|EV;FI=999;CL=1;NA=Home v Away;FS=1;OI=888;|"
            "MA;FI=888;ID=1777;IT=L999-1777_1_3;NA=Fulltime Result;|"
            "PA;FI=888;ID=1;IT=L888-1_1_3;NA=Home;OD=2/1;OR=0;|"
        )

        state.apply_body("D|", path="OVL888-1_1_3")

        self.assertNotIn("L888-1_1_3", state.selections)

    def test_timer_runs_for_live_without_tu(self) -> None:
        from bet365.mapper import _timer_payload
        from bet365.state import EventState

        event = EventState(fi=1, minute=73, timer_secs=0, live=True)
        payload = _timer_payload(event)
        self.assertEqual(payload["timer_display"], "73:00")
        self.assertEqual(payload["score_function"], "run")
        self.assertEqual(payload["timer_seconds"], 73 * 60)

    def test_timer_frozen_on_break(self) -> None:
        from bet365.mapper import _timer_payload
        from bet365.state import EventState

        event = EventState(
            fi=1, minute=45, timer_secs=0, timer_ticking=False, live=True
        )
        payload = _timer_payload(event)
        self.assertEqual(payload["timer_display"], "45:00")
        self.assertEqual(payload["score_function"], "stop")

    def test_timer_hides_untrusted_zero_minute_clock(self) -> None:
        from bet365.mapper import _timer_payload
        from bet365.state import EventState

        event = EventState(fi=1, minute=0, timer_secs=22, timer_ticking=True, live=True)
        self.assertEqual(_timer_payload(event), {})

    def test_timer_uses_tu_when_ticking(self) -> None:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from bet365.mapper import _timer_payload
        from bet365.state import EventState

        london = ZoneInfo("Europe/London")
        # Period sync ~2 minutes ago, feed says TM=10 TS=0 → ~12'
        sync = datetime.now(tz=london) - timedelta(minutes=2, seconds=5)
        tu = sync.strftime("%Y%m%d%H%M%S")
        event = EventState(
            fi=1,
            minute=10,
            timer_secs=0,
            timer_ticking=True,
            timer_tu=tu,
            live=True,
        )
        payload = _timer_payload(event)
        self.assertEqual(payload["score_function"], "run")
        self.assertGreaterEqual(payload["timer_seconds"], 10 * 60 + 120)
        self.assertLess(payload["timer_seconds"], 10 * 60 + 180)
        self.assertRegex(payload["timer_display"], r"^\d+:\d{2}$")

    def test_map_score_timer_stop_on_break(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=501;CL=1;NA=Home v Away;FS=1;SS=1-0;TM=45;TS=0;TT=0;OI=502;|"
            "MA;FI=502;ID=1777;NA=Fulltime Result;|"
            "PA;FI=502;ID=1;IT=L502-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=502;ID=2;IT=L502-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=502;ID=3;IT=L502-3_1;NA=Away;OD=4/1;OR=2;|"
        )
        changes = map_state_to_changes(state)
        score = next(c for c in changes if c.change_type.value == "score")
        self.assertEqual(score.payload["timer_display"], "45:00")
        self.assertEqual(score.payload["score_function"], "stop")


if __name__ == "__main__":
    unittest.main()
