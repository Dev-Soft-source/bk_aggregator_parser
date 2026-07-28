"""Tests for Fonbet HTTP client retry behavior."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from fonbet.api import FonbetApiError, _is_retryable, fetch_packet


class FonbetApiRetryTests(unittest.TestCase):
    def test_is_retryable_ssl_and_connection(self) -> None:
        self.assertTrue(_is_retryable(requests.exceptions.SSLError("ssl")))
        self.assertTrue(_is_retryable(requests.exceptions.ConnectionError("conn")))
        self.assertTrue(_is_retryable(requests.exceptions.Timeout("t")))
        self.assertFalse(_is_retryable(ValueError("bad")))

    @patch("fonbet.api.time.sleep")
    @patch("fonbet.api.requests.Session")
    def test_fetch_packet_retries_transient_ssl(
        self,
        session_cls: MagicMock,
        sleep_mock: MagicMock,
    ) -> None:
        session = MagicMock()
        session_cls.return_value = session
        ok_response = MagicMock()
        ok_response.json.return_value = {"packetVersion": 1}
        ok_response.raise_for_status.return_value = None
        session.get.side_effect = [
            requests.exceptions.SSLError("eof"),
            ok_response,
        ]

        data = fetch_packet("https://example.test/packet", attempts=3, retry_sleep=0.01)
        self.assertEqual(data["packetVersion"], 1)
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_called_once()
        self.assertEqual(session.close.call_count, 2)

    @patch("fonbet.api.requests.Session")
    def test_fetch_packet_rejects_non_object_json(self, session_cls: MagicMock) -> None:
        session = MagicMock()
        session_cls.return_value = session
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        session.get.return_value = response

        with self.assertRaises(FonbetApiError):
            fetch_packet("https://example.test/packet", attempts=1)


if __name__ == "__main__":
    unittest.main()
