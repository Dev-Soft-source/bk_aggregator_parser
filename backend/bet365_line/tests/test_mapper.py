"""Tests for bet365_line place=line mapping and hub URL."""

from __future__ import annotations

import unittest

from bet365.cloudflare_gate import is_live_hub_url
from bet365.state import ZapFeedState
from bet365_line.config import DEFAULT_BROWSER_CDP_URL, DEFAULT_BROWSER_URL
from bet365_line.mapper import map_state_to_changes


class Bet365LineMapperTests(unittest.TestCase):
    def test_live_fs1_events_are_skipped(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        # FS=1 is in-play — must not land in place=line.
        state.apply_body(
            "F|EV;FI=501;CL=1;NA=Home v Away;CT=League;FS=1;OI=502;|"
            "MA;FI=502;ID=1777;NA=Fulltime Result;|"
            "PA;FI=502;ID=1;IT=L502-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=502;ID=2;IT=L502-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=502;ID=3;IT=L502-3_1;NA=Away;OD=4/1;OR=2;|"
        )
        changes = map_state_to_changes(state)
        self.assertEqual(changes, [])

    def test_prematch_fs0_place_line(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=601;CL=1;NA=Alpha v Beta;CT=League;FS=0;OI=602;|"
            "MA;FI=602;ID=1777;NA=Fulltime Result;|"
            "PA;FI=602;ID=1;IT=L602-1_1;NA=Alpha;OD=11/10;OR=0;|"
            "PA;FI=602;ID=2;IT=L602-2_1;NA=Draw;OD=12/5;OR=1;|"
            "PA;FI=602;ID=3;IT=L602-3_1;NA=Beta;OD=11/5;OR=2;|"
        )
        changes = map_state_to_changes(state)
        fixtures = [c for c in changes if c.change_type.value == "fixture"]
        scores = [c for c in changes if c.change_type.value == "score"]
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].payload["place"], "line")
        self.assertFalse(fixtures[0].payload["live"])
        self.assertEqual(scores, [])


class Bet365LineConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(DEFAULT_BROWSER_URL, "https://www.bet365.com/#/AO/")
        self.assertEqual(DEFAULT_BROWSER_CDP_URL, "http://127.0.0.1:9225")
        from bet365_line.config import DEFAULT_BROWSER_ENTRY_URL

        self.assertEqual(DEFAULT_BROWSER_ENTRY_URL, "https://www.bet365.com/#/HO/")
        self.assertIn("#/AO/", DEFAULT_BROWSER_URL)

    def test_line_config_imports_live_cdp_by_default(self) -> None:
        from bet365_line.config import line_config_from_env

        cfg = line_config_from_env()
        self.assertEqual(cfg.browser_cookie_import_cdp_url, "http://127.0.0.1:9223")

    def test_ao_is_hub_url(self) -> None:
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/AO/"))
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/AS/B1/"))


if __name__ == "__main__":
    unittest.main()
