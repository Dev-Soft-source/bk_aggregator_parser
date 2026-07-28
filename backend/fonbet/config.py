import os
from dataclasses import dataclass
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

DEFAULT_LIST_LIGHT_URL = (
    "https://line-lb61-w.bk6bba-resources.com/ma/events/listLight"
    "?lang=en&place=live&scopeMarket=1600"
)
DEFAULT_LIST_URL_BASE = (
    "https://line-lb54-w.bk6bba-resources.com/ma/events/list"
)
DEFAULT_POLL_INTERVAL = 3.0
# Connect fails fast; read allows large listLight JSON.
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 20.0

@dataclass(frozen=True)
class FonbetApiConfig:
    list_light_url: str
    list_url_base: str
    scope_market: int
    lang: str
    poll_interval: float
    timeout: float  # read timeout (legacy env FONBET_HTTP_TIMEOUT)
    connect_timeout: float
    # Re-fetch listLight every N polls so absent/finished matches prune from DB.
    # 0 disables periodic snapshots (only startup / error reset).
    snapshot_every: int
    # Drop place=line rows whose kickoff is older than now - grace (hours).
    # 0 = delete as soon as start_time is in the past.
    line_past_grace_hours: int
    # Transient HTTP retries (SSL EOF, connection reset, timeout).
    http_retries: int
    http_retry_sleep: float
    # Extra poll-loop backoff cap after consecutive failures (seconds).
    failure_backoff_max: float

    @classmethod
    def from_env(cls) -> "FonbetApiConfig":
        # Prefer explicit connect timeout; fall back to legacy single timeout for read.
        read_timeout = float(os.getenv("FONBET_HTTP_TIMEOUT", str(DEFAULT_READ_TIMEOUT)))
        connect_timeout = float(
            os.getenv("FONBET_HTTP_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT))
        )
        return cls(
            list_light_url=os.getenv("FONBET_LIST_LIGHT_URL", DEFAULT_LIST_LIGHT_URL),
            list_url_base=os.getenv("FONBET_LIST_URL_BASE", DEFAULT_LIST_URL_BASE),
            scope_market=int(os.getenv("FONBET_SCOPE_MARKET", "1600")),
            lang=os.getenv("FONBET_LANG", "en"),
            poll_interval=float(os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL))),
            timeout=read_timeout,
            connect_timeout=connect_timeout,
            snapshot_every=int(os.getenv("FONBET_SNAPSHOT_EVERY", "20")),
            line_past_grace_hours=int(os.getenv("FONBET_LINE_PAST_GRACE_HOURS", "0")),
            http_retries=int(os.getenv("FONBET_HTTP_RETRIES", "3")),
            http_retry_sleep=float(os.getenv("FONBET_HTTP_RETRY_SLEEP", "2")),
            failure_backoff_max=float(os.getenv("FONBET_FAILURE_BACKOFF_MAX", "60")),
        )

    @property
    def request_timeout(self) -> tuple[float, float]:
        """requests timeout=(connect, read)."""
        return (self.connect_timeout, self.timeout)

    def list_url(self, version: int) -> str:
        query = urlencode(
            {
                "lang": self.lang,
                "version": version,
                "scopeMarket": self.scope_market,
            }
        )
        return f"{self.list_url_base}?{query}"
