"""Betcity live WebSocket configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_WS_URL = "wss://sc.betcity.ru/?id=live&csn=ooca9s"
DEFAULT_ORIGIN = "https://betcity.ru"
DEFAULT_REFERER = "https://betcity.ru/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_LISTEN_SECONDS = 30.0
DEFAULT_POLL_INTERVAL = 3.5
DEFAULT_SITE_NAME = "betcity.ru"
DEFAULT_CATALOG_URL = "https://ad.betcity.ru/d/on_air/events"
DEFAULT_CATALOG_REFRESH_SECONDS = 30.0
DEFAULT_BROWSER_CDP_URL = "http://127.0.0.1:9224"
DEFAULT_BROWSER_URL = "https://betcity.ru/ru/live"
DEFAULT_BROWSER_TIMEOUT_SECONDS = 60.0

# Historical / truncated aliases that must never be used for writes.
SITE_NAME_ALIASES: dict[str, str] = {
    "betcity": DEFAULT_SITE_NAME,
    "betcity.": DEFAULT_SITE_NAME,
    "betcity.r": DEFAULT_SITE_NAME,
}


def normalize_site_name(name: str | None) -> str:
    """Always resolve to a canonical Betcity site name."""
    raw = (name or "").strip() or DEFAULT_SITE_NAME
    return SITE_NAME_ALIASES.get(raw.lower(), raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def normalize_proxy(raw: str | None) -> str | None:
    """Return a requests-compatible proxy URL, or None."""
    value = (raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        return f"http://{value}"
    return value


def chrome_proxy_server(proxy: str | None) -> str | None:
    """Host:port form for Chrome --proxy-server."""
    normalized = normalize_proxy(proxy)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None
    if parsed.port:
        return f"{parsed.hostname}:{parsed.port}"
    return parsed.hostname


def requests_proxies(proxy: str | None) -> dict[str, str] | None:
    normalized = normalize_proxy(proxy)
    if not normalized:
        return None
    return {"http": normalized, "https": normalized}


@dataclass(frozen=True)
class BetcityConfig:
    ws_url: str
    origin: str
    referer: str
    cookie: str | None
    user_agent: str
    listen_seconds: float
    poll_interval: float = DEFAULT_POLL_INTERVAL
    catalog_url: str = DEFAULT_CATALOG_URL
    catalog_refresh_seconds: float = DEFAULT_CATALOG_REFRESH_SECONDS
    use_browser: bool = False
    browser_cdp_url: str = DEFAULT_BROWSER_CDP_URL
    browser_url: str = DEFAULT_BROWSER_URL
    browser_timeout_seconds: float = DEFAULT_BROWSER_TIMEOUT_SECONDS
    proxy: str | None = None
    max_frames: int | None = None

    @classmethod
    def from_env(cls) -> "BetcityConfig":
        cookie = os.getenv("BETCITY_COOKIE", "").strip() or None
        proxy = normalize_proxy(os.getenv("BETCITY_PROXY"))
        cdp_url = (
            os.getenv("BETCITY_BROWSER_CDP_URL", "").strip() or DEFAULT_BROWSER_CDP_URL
        )
        return cls(
            ws_url=os.getenv("BETCITY_WS_URL", DEFAULT_WS_URL).strip() or DEFAULT_WS_URL,
            origin=os.getenv("BETCITY_ORIGIN", DEFAULT_ORIGIN).strip() or DEFAULT_ORIGIN,
            referer=os.getenv("BETCITY_REFERER", DEFAULT_REFERER).strip() or DEFAULT_REFERER,
            cookie=cookie,
            user_agent=(
                os.getenv("BETCITY_USER_AGENT", DEFAULT_USER_AGENT).strip()
                or DEFAULT_USER_AGENT
            ),
            listen_seconds=float(
                os.getenv("BETCITY_LISTEN_SECONDS", str(DEFAULT_LISTEN_SECONDS))
            ),
            poll_interval=float(
                os.getenv("BETCITY_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL))
            ),
            catalog_url=(
                os.getenv("BETCITY_CATALOG_URL", DEFAULT_CATALOG_URL).strip()
                or DEFAULT_CATALOG_URL
            ),
            catalog_refresh_seconds=float(
                os.getenv(
                    "BETCITY_CATALOG_REFRESH_SECONDS",
                    str(DEFAULT_CATALOG_REFRESH_SECONDS),
                )
            ),
            use_browser=_env_bool("BETCITY_USE_BROWSER", False),
            browser_cdp_url=cdp_url,
            browser_url=(
                os.getenv("BETCITY_BROWSER_URL", DEFAULT_BROWSER_URL).strip()
                or DEFAULT_BROWSER_URL
            ),
            browser_timeout_seconds=float(
                os.getenv(
                    "BETCITY_BROWSER_TIMEOUT_SECONDS",
                    str(DEFAULT_BROWSER_TIMEOUT_SECONDS),
                )
            ),
            proxy=proxy,
        )

    def ws_query(self) -> dict[str, list[str]]:
        """Parse query params from the WebSocket URL."""
        return parse_qs(urlparse(self.ws_url).query)

    def channel_id(self) -> str | None:
        values = self.ws_query().get("id")
        return values[0] if values else None

    def csn(self) -> str | None:
        values = self.ws_query().get("csn")
        return values[0] if values else None

    def ws_headers(self) -> dict[str, str]:
        headers = {
            "Origin": self.origin,
            "User-Agent": self.user_agent,
            "Referer": self.referer,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def requests_proxies(self) -> dict[str, str] | None:
        return requests_proxies(self.proxy)
