"""Tests for CDP Chrome launcher script selection."""

from __future__ import annotations

import unittest

from bet365.browser_session import _chrome_launch_script_for_cdp


class ChromeLaunchScriptTests(unittest.TestCase):
    def test_line_port_uses_line_script(self) -> None:
        script = _chrome_launch_script_for_cdp("http://127.0.0.1:9225")
        self.assertEqual(script.name, "start_chrome_cdp_bet365_line.ps1")

    def test_live_port_uses_live_script(self) -> None:
        script = _chrome_launch_script_for_cdp("http://127.0.0.1:9223")
        self.assertEqual(script.name, "start_chrome_cdp_bet365.ps1")


if __name__ == "__main__":
    unittest.main()
