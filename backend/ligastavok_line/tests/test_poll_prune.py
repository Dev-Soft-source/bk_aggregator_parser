"""Tests for line absent-match prune gating."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from adapters.base import ChangeType
from ligastavok_line.poll_loop import should_prune_line_absent


def _change(
    *,
    match_id: int = 1,
    change_type: ChangeType = ChangeType.FIXTURE,
    from_version: int | None = None,
) -> MagicMock:
    c = MagicMock()
    c.change_type = change_type
    c.match_payload_id = match_id
    c.from_version = from_version
    return c


class ShouldPruneLineAbsentTests(unittest.TestCase):
    def test_prunes_full_http_prematch_snapshot(self) -> None:
        changes = [_change(match_id=10), _change(match_id=20)]
        do_prune, ids = should_prune_line_absent(
            changes,
            snapshot_ns="prematch",
            prune_enabled=True,
            min_fixtures=1,
        )
        self.assertTrue(do_prune)
        self.assertEqual(ids, {10, 20})

    def test_skips_websocket_deltas(self) -> None:
        changes = [_change(match_id=10, from_version=99)]
        do_prune, ids = should_prune_line_absent(
            changes,
            snapshot_ns="prematch",
            prune_enabled=True,
        )
        self.assertFalse(do_prune)
        self.assertEqual(ids, {10})

    def test_skips_when_disabled(self) -> None:
        changes = [_change(match_id=10)]
        do_prune, _ = should_prune_line_absent(
            changes,
            snapshot_ns="prematch",
            prune_enabled=False,
        )
        self.assertFalse(do_prune)

    def test_skips_live_ns(self) -> None:
        changes = [_change(match_id=10)]
        do_prune, _ = should_prune_line_absent(
            changes,
            snapshot_ns="live",
            prune_enabled=True,
        )
        self.assertFalse(do_prune)

    def test_respects_min_fixtures(self) -> None:
        changes = [_change(match_id=10)]
        do_prune, ids = should_prune_line_absent(
            changes,
            snapshot_ns="prematch",
            prune_enabled=True,
            min_fixtures=5,
        )
        self.assertFalse(do_prune)
        self.assertEqual(ids, {10})


if __name__ == "__main__":
    unittest.main()
