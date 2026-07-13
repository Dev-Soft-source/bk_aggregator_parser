"""Unit tests for live-data retention helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from retention import prune_absent_matches


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


if __name__ == "__main__":
    unittest.main()
