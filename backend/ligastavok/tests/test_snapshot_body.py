"""Tests for Liga Stavok eventsList POST body builder."""

from __future__ import annotations

import unittest

from ligastavok.snapshot_body import apply_live_all, live_all_body, parse_body, serialize_body


class SnapshotBodyTests(unittest.TestCase):
    def test_live_all_strips_game_filter(self) -> None:
        body = apply_live_all(
            parse_body(
                '{"gameId":[23462],"limit":80,"view":"priority","proposedTypes":["MAINOFFER"]}'
            )
        )
        self.assertEqual(body["ns"], "live")
        self.assertNotIn("gameId", body)

    def test_serialize_skip(self) -> None:
        raw = serialize_body(live_all_body(), skip=80)
        self.assertIn('"skip":80', raw)
        self.assertIn('"ns":"live"', raw)


if __name__ == "__main__":
    unittest.main()
