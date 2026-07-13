"""Betcity prematch (line) HTTP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://ad.betcity.ru/d/off/events"
DEFAULT_REV = "6"
DEFAULT_VER = "82"
DEFAULT_CSN = "ooca9s"
DEFAULT_ADD = "dep_events"
DEFAULT_POLL_INTERVAL = 10.0
# Full /d/off/events payloads are large; 30s often times out on slow links.
DEFAULT_TIMEOUT = 90.0
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_SITE_NAME = "betcity.ru"
DEFAULT_MAX_BACKOFF = 120.0
# After this many consecutive network failures, force a fresh snapshot.
DEFAULT_RESET_AFTER_FAILURES = 5

OTHER_BOOKMAKER_SITES = frozenset(
    {"fonbet.com", "bet365.com", "ligastavok.ru", "betcity", "betcity."}
)


def normalize_site_name(name: str | None) -> str:
    raw = (name or "").strip() or DEFAULT_SITE_NAME
    if raw.lower() in OTHER_BOOKMAKER_SITES or raw in OTHER_BOOKMAKER_SITES:
        return DEFAULT_SITE_NAME
    if raw in {"betcity", "betcity.", "betcity.r"}:
        return DEFAULT_SITE_NAME
    return raw


@dataclass(frozen=True)
class BetcityLineConfig:
    base_url: str
    rev: str
    ver: str
    csn: str
    add: str
    poll_interval: float
    timeout: float
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    max_backoff: float = DEFAULT_MAX_BACKOFF
    reset_after_failures: int = DEFAULT_RESET_AFTER_FAILURES
    site_name: str = DEFAULT_SITE_NAME

    @classmethod
    def from_env(cls) -> "BetcityLineConfig":
        return cls(
            base_url=(
                os.getenv("BETCITY_LINE_URL", DEFAULT_BASE_URL).strip()
                or DEFAULT_BASE_URL
            ),
            rev=os.getenv("BETCITY_LINE_REV", DEFAULT_REV).strip() or DEFAULT_REV,
            ver=os.getenv("BETCITY_LINE_VER", DEFAULT_VER).strip() or DEFAULT_VER,
            csn=os.getenv("BETCITY_LINE_CSN", DEFAULT_CSN).strip() or DEFAULT_CSN,
            add=os.getenv("BETCITY_LINE_ADD", DEFAULT_ADD).strip() or DEFAULT_ADD,
            poll_interval=float(
                os.getenv(
                    "BETCITY_LINE_POLL_INTERVAL_SECONDS",
                    str(DEFAULT_POLL_INTERVAL),
                )
            ),
            timeout=float(os.getenv("BETCITY_LINE_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT))),
            connect_timeout=float(
                os.getenv(
                    "BETCITY_LINE_CONNECT_TIMEOUT",
                    str(DEFAULT_CONNECT_TIMEOUT),
                )
            ),
            max_backoff=float(
                os.getenv("BETCITY_LINE_MAX_BACKOFF", str(DEFAULT_MAX_BACKOFF))
            ),
            reset_after_failures=int(
                os.getenv(
                    "BETCITY_LINE_RESET_AFTER_FAILURES",
                    str(DEFAULT_RESET_AFTER_FAILURES),
                )
            ),
            site_name=normalize_site_name(
                os.getenv("BETCITY_LINE_SITE_NAME") or DEFAULT_SITE_NAME
            ),
        )

    def request_timeout(self) -> tuple[float, float]:
        """(connect, read) timeouts for requests."""
        return (self.connect_timeout, self.timeout)

    def _query(self, *, md: int | None = None) -> dict[str, str]:
        query = {
            "rev": self.rev,
            "add": self.add,
            "ver": self.ver,
            "csn": self.csn,
        }
        if md is not None:
            query["md"] = str(int(md))
        return query

    def snapshot_url(self) -> str:
        return self._build_url(self._query())

    def delta_url(self, md: int) -> str:
        return self._build_url(self._query(md=md))

    def _build_url(self, query: dict[str, str]) -> str:
        parsed = urlparse(self.base_url)
        existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
        existing.update(query)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(existing),
                parsed.fragment,
            )
        )
