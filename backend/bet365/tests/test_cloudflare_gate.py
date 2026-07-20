"""Tests for Cloudflare challenge detection."""

from __future__ import annotations

import unittest

from bet365.cloudflare_gate import (
    is_bet365_authenticated,
    is_bet365_live_ready,
    is_cloudflare_challenge,
    is_live_hub_url,
    is_usa_geo_gate,
)


class CloudflareGateTests(unittest.TestCase):
    def test_live_hub_url(self) -> None:
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/HO/"))
        self.assertTrue(is_live_hub_url("https://www.bet365.com/#/AO/"))
        self.assertFalse(is_live_hub_url("https://www.bet365.com/"))

    def test_usa_geo_gate_url(self) -> None:
        self.assertTrue(
            is_usa_geo_gate(url="https://www.bet365.com/usa?isoCode=US&gcsid=DC")
        )
        self.assertTrue(
            is_usa_geo_gate(
                url="https://www.bet365.com/",
                body_text="Where do you want to play?\nNew Jersey\nColorado",
            )
        )

    def test_usa_geo_not_authenticated(self) -> None:
        self.assertFalse(
            is_bet365_authenticated(
                url="https://www.bet365.com/usa?isoCode=US",
                title="bet365",
                body_text="Where do you want to play?",
            )
        )

    def test_ao_hub_is_live_ready(self) -> None:
        self.assertTrue(
            is_bet365_live_ready(url="https://www.bet365.com/#/AO/")
        )

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
