"""Tests for Cloudflare challenge detection."""

from __future__ import annotations

import unittest

from bet365.cloudflare_gate import is_bet365_live_ready, is_cloudflare_challenge, is_live_hub_url


class CloudflareGateTests(unittest.TestCase):
    def test_live_hub_url(self) -> None:
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/HO/"))
        self.assertFalse(is_live_hub_url("https://www.bet365.com/"))

    def test_detects_turnstile_page(self) -> None:
        self.assertTrue(
            is_cloudflare_challenge(
                url="https://www.bet365.com/",
                title="Performing security verification",
                body_text="Verify you are human",
            )
        )

    def test_detects_cdn_cgi_url(self) -> None:
        self.assertTrue(
            is_cloudflare_challenge(
                url="https://www.bet365.com/cdn-cgi/challenge-platform/h/g/flow/ov1/",
                title="",
                body_text="",
            )
        )

    def test_bet365_authenticated_with_pstk(self) -> None:
        from bet365.cloudflare_gate import is_bet365_authenticated

        self.assertTrue(
            is_bet365_authenticated(
                url="https://www.bet365.com/",
                title="bet365",
                body_text="Sports",
                has_pstk=True,
            )
        )

    def test_bet365_live_ready_with_pstk(self) -> None:
        from bet365.cloudflare_gate import is_bet365_live_ready

        self.assertTrue(
            is_bet365_live_ready(
                url="https://www.bet365.com/#/HO/",
                title="bet365",
                body_text="In-Play",
                has_pstk=True,
            )
        )

    def test_bet365_not_ready_during_challenge(self) -> None:
        from bet365.cloudflare_gate import is_bet365_authenticated, is_bet365_live_ready

        self.assertFalse(
            is_bet365_authenticated(
                url="https://www.bet365.com/",
                title="Performing security verification",
                body_text="Verify you are human",
                has_pstk=False,
            )
        )
        self.assertFalse(
            is_bet365_live_ready(
                url="https://www.bet365.com/",
                title="Performing security verification",
                body_text="Verify you are human",
                has_pstk=False,
            )
        )

    def test_bet365_live_ready_with_zap_socket(self) -> None:
        from bet365.cloudflare_gate import is_bet365_live_ready

        self.assertTrue(
            is_bet365_live_ready(
                url="https://www.bet365.com/#/HO/",
                title="bet365",
                body_text="",
                has_zap_socket=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
