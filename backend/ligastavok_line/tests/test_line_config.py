"""Tests for Liga Stavok line-specific config."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ligastavok_line.config import line_config_from_env


class LineConfigTests(unittest.TestCase):
    def test_forces_prematch_namespace(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LIGASTAVOK_NS": "live",
                "LIGASTAVOK_LINE_POLL_INTERVAL_SECONDS": "12",
            },
            clear=False,
        ):
            cfg = line_config_from_env()
        self.assertEqual(cfg.snapshot_ns, "prematch")
        self.assertFalse(cfg.ws_enabled)
        self.assertEqual(cfg.poll_interval, 12.0)

    def test_browser_url_is_prematch_not_live(self) -> None:
        from ligastavok_line.config import LINE_BROWSER_URL

        with patch.dict(
            os.environ,
            {
                "LIGASTAVOK_BROWSER_URL": "https://www.ligastavok.ru/live",
                "LIGASTAVOK_LINE_BROWSER_URL": "https://www.ligastavok.ru/live",
            },
            clear=False,
        ):
            cfg = line_config_from_env()
        self.assertEqual(cfg.browser_url, LINE_BROWSER_URL)
        self.assertEqual(
            cfg.request_headers()["Referer"],
            "https://www.ligastavok.ru/prematch",
        )


if __name__ == "__main__":
    unittest.main()
