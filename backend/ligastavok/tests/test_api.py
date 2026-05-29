"""Unit tests for Liga Stavok HTTP client helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ligastavok.api import parse_curl_file


class ParseCurlTests(unittest.TestCase):
    def test_parse_post_events_list(self) -> None:
        curl = """curl 'https://lds-api-sites.ligastavok.ru/rest/events/v8/eventsList' \\
  -H 'content-type: application/json' \\
  -H 'cookie: session=abc123' \\
  --data-raw '{"ns":"live","limit":40,"skip":0}'"""
        with tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False, encoding="utf-8") as handle:
            handle.write(curl)
            path = Path(handle.name)

        try:
            req = parse_curl_file(path)
        finally:
            path.unlink()

        self.assertEqual(req.method, "POST")
        self.assertIn("eventsList", req.url)
        self.assertEqual(req.headers["Cookie"], "session=abc123")
        self.assertEqual(req.headers["Content-Type"], "application/json")
        self.assertEqual(req.body, '{"ns":"live","limit":40,"skip":0}')

    def test_parse_post_with_cookie_b_flag(self) -> None:
        curl = """curl 'https://lds-api-sites.ligastavok.ru/rest/events/v8/eventsList' \\
  -X POST \\
  -b 'session=abc; qrator=xyz' \\
  --data-raw '{"ns":"live","limit":20}'"""
        with tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False, encoding="utf-8") as handle:
            handle.write(curl)
            path = Path(handle.name)
        try:
            req = parse_curl_file(path)
        finally:
            path.unlink()
        self.assertEqual(req.headers["Cookie"], "session=abc; qrator=xyz")
        self.assertEqual(req.body, '{"ns":"live","limit":20}')

    def test_parse_windows_cmd_curl(self) -> None:
        curl = r'''curl ^"https://lds-api-sites.ligastavok.ru/rest/events/v8/eventsList^" ^
  -H ^"Referer: https://www.ligastavok.ru/^" ^
  -H ^"content-type: application/json^" ^
  --data-raw ^"^{^\^"gameId^\^":^[^],^\^"limit^\^":40^}^"'''
        with tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False, encoding="utf-8") as handle:
            handle.write(curl)
            path = Path(handle.name)
        try:
            req = parse_curl_file(path)
        finally:
            path.unlink()

        self.assertEqual(req.method, "POST")
        self.assertIn("eventsList", req.url)
        self.assertEqual(req.headers["Referer"], "https://www.ligastavok.ru/")
        self.assertEqual(req.body, '{"gameId":[],"limit":40}')

    def test_parse_real_capture_curl_file(self) -> None:
        path = Path(__file__).resolve().parents[2] / "capture.curl"
        if not path.is_file():
            self.skipTest("capture.curl not present")
        req = parse_curl_file(path)
        self.assertIn("eventsList", req.url)
        self.assertEqual(req.method, "POST")
        if req.body:
            self.assertIn("gameId", req.body)

    def test_parse_all_headers_including_user_agent(self) -> None:
        curl = """curl 'https://example.com/api' \\
  -H 'User-Agent: Chrome/148' \\
  -H 'accept: application/json' \\
  -H 'x-application-name: mobile'"""
        with tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False, encoding="utf-8") as handle:
            handle.write(curl)
            path = Path(handle.name)
        try:
            req = parse_curl_file(path)
        finally:
            path.unlink()
        self.assertEqual(req.headers["User-Agent"], "Chrome/148")
        self.assertEqual(req.headers["accept"], "application/json")


if __name__ == "__main__":
    unittest.main()
