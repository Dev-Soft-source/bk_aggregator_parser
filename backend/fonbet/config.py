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

    @classmethod
    def from_env(cls) -> "FonbetApiConfig":
        return cls(
            list_light_url=os.getenv("FONBET_LIST_LIGHT_URL", DEFAULT_LIST_LIGHT_URL),
            list_url_base=os.getenv("FONBET_LIST_URL_BASE", DEFAULT_LIST_URL_BASE),
            scope_market=int(os.getenv("FONBET_SCOPE_MARKET", "1600")),
            lang=os.getenv("FONBET_LANG", "en"),
            poll_interval=float(os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL))),
            timeout=float(os.getenv("FONBET_HTTP_TIMEOUT", "30")),
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
