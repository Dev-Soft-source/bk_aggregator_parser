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

@dataclass(frozen=True)
class FonbetApiConfig:
    list_light_url: str
    list_url_base: str
    scope_market: int
    lang: str
    poll_interval: float
    timeout: float
    # Re-fetch listLight every N polls so absent/finished matches prune from DB.
    # 0 disables periodic snapshots (only startup / error reset).
    snapshot_every: int
    # Drop place=line rows whose kickoff is older than now - grace (hours).
    # 0 = delete as soon as start_time is in the past.
    line_past_grace_hours: int

    @classmethod
    def from_env(cls) -> "FonbetApiConfig":
        return cls(
            list_light_url=os.getenv("FONBET_LIST_LIGHT_URL", DEFAULT_LIST_LIGHT_URL),
            list_url_base=os.getenv("FONBET_LIST_URL_BASE", DEFAULT_LIST_URL_BASE),
            scope_market=int(os.getenv("FONBET_SCOPE_MARKET", "1600")),
            lang=os.getenv("FONBET_LANG", "en"),
            poll_interval=float(os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL))),
            timeout=float(os.getenv("FONBET_HTTP_TIMEOUT", "30")),
            snapshot_every=int(os.getenv("FONBET_SNAPSHOT_EVERY", "20")),
            line_past_grace_hours=int(os.getenv("FONBET_LINE_PAST_GRACE_HOURS", "0")),
        )

    def list_url(self, version: int) -> str:
        query = urlencode(
            {
                "lang": self.lang,
                "version": version,
                "scopeMarket": self.scope_market,
            }
        )
        return f"{self.list_url_base}?{query}"
