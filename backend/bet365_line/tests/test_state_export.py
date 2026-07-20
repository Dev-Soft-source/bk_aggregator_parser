"""Tests for bet365_line prematch export."""

from __future__ import annotations

import unittest

from bet365.state import ZapFeedState
from bet365_line.state_export import prematch_events_with_odds


class LineStateExportTests(unittest.TestCase):
    def test_prematch_with_score_not_dropped(self) -> None:
        """Shared export_events drops prematch with SS; line export keeps them."""
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=701;CL=1;NA=Home v Away;CT=League;FS=0;SS=1-0;OI=702;|"
            "MA;FI=702;ID=1777;NA=Fulltime Result;|"
            "PA;FI=702;ID=1;IT=L702-1_1;NA=Home;OD=2/1;OR=0;|"
            "PA;FI=702;ID=2;IT=L702-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=702;ID=3;IT=L702-3_1;NA=Away;OD=4/1;OR=2;|"
        )
        shared = state.export_events(live_only=False)
        line = prematch_events_with_odds(state)
        self.assertEqual(len(shared), 0)
        self.assertEqual(len(line), 1)

    def test_live_events_excluded(self) -> None:
        state = ZapFeedState()
        state.sport_classes[1] = "Soccer"
        state.apply_body(
            "F|EV;FI=801;CL=1;NA=A v B;CT=League;FS=1;OI=802;|"
            "MA;FI=802;ID=1777;NA=Fulltime Result;|"
            "PA;FI=802;ID=1;IT=L802-1_1;NA=A;OD=2/1;OR=0;|"
            "PA;FI=802;ID=2;IT=L802-2_1;NA=Draw;OD=3/1;OR=1;|"
            "PA;FI=802;ID=3;IT=L802-3_1;NA=B;OD=4/1;OR=2;|"
        )
        self.assertEqual(prematch_events_with_odds(state), [])


if __name__ == "__main__":
    unittest.main()
