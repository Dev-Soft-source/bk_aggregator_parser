"""Unit tests for live-data retention helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from retention import delete_matches_by_ids, prune_absent_matches, prune_past_place_matches


class PruneAbsentMatchesTests(unittest.TestCase):
    def test_refuses_empty_keep_set(self) -> None:
        cur = MagicMock()
        deleted = prune_absent_matches(cur, site_id=1, keep_match_ids=[])
        self.assertEqual(deleted, 0)
        cur.execute.assert_not_called()

    def test_deletes_absent_live_matches(self) -> None:
        cur = MagicMock()
        cur.rowcount = 3
        deleted = prune_absent_matches(cur, site_id=7, keep_match_ids={10, 20})
        self.assertEqual(deleted, 3)
        sql, params = cur.execute.call_args[0]
        self.assertIn("DELETE FROM matches", sql)
        self.assertEqual(params[0], 7)
        self.assertEqual(params[1], "live")
        self.assertEqual(params[2], [10, 20])


class PrunePastPlaceMatchesTests(unittest.TestCase):
    def test_grace_negative_noop(self) -> None:
        cur = MagicMock()
        deleted = prune_past_place_matches(cur, site_id=1, place="line", grace_hours=-1)
        self.assertEqual(deleted, 0)
        cur.execute.assert_not_called()

    def test_deletes_past_line_kickoffs(self) -> None:
        cur = MagicMock()
        cur.rowcount = 5
        deleted = prune_past_place_matches(cur, site_id=3, place="line", grace_hours=0)
        self.assertEqual(deleted, 5)
        sql, params = cur.execute.call_args[0]
        self.assertIn("DELETE FROM matches", sql)
        self.assertIn("start_time", sql)
        self.assertEqual(params[0], 3)
        self.assertEqual(params[1], "line")
        self.assertEqual(params[2], 0)


class DeleteMatchesByIdsTests(unittest.TestCase):
    def test_empty_noop(self) -> None:
        cur = MagicMock()
        self.assertEqual(delete_matches_by_ids(cur, 1, []), 0)
        cur.execute.assert_not_called()

    def test_deletes_ids(self) -> None:
        cur = MagicMock()
        cur.rowcount = 2
        deleted = delete_matches_by_ids(cur, 9, {11, 12}, place="live")
        self.assertEqual(deleted, 2)
        sql, params = cur.execute.call_args[0]
        self.assertIn("DELETE FROM matches", sql)
        self.assertEqual(params[0], 9)
        self.assertEqual(params[1], "live")
        self.assertEqual(params[2], [11, 12])


if __name__ == "__main__":
    unittest.main()
