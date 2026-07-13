"""Bet365 WebSocket / ZAP protocol configuration."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_WS_BASE = "wss://premws-pt1.365lpodds.com/zap/"
DEFAULT_WS_AUX_BASE = "wss://pshudws.365lpodds.com/zap/"
DEFAULT_ORIGIN = "https://www.bet365.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_BROWSER_ENTRY_URL = "https://www.bet365.com/"
DEFAULT_BROWSER_URL = "https://www.bet365.com/#/HO/"
DEFAULT_BROWSER_CDP_URL = "http://127.0.0.1:9223"
DEFAULT_BROWSER_TIMEOUT = 90.0
DEFAULT_POLL_INTERVAL = 3.5
DEFAULT_SAFE_POLL_INTERVAL = 8.0
DEFAULT_STALE_POLLS_SAFE = 6
DEFAULT_STALE_POLLS = 3
DEFAULT_CLOUDFLARE_WAIT_SECONDS = 300.0
DEFAULT_CLOUDFLARE_AUTO_CLICK_DELAY = 30.0
DEFAULT_COOKIE_BANNER_DELAY_SECONDS = 5.0
DEFAULT_TOPICS = (
    "__host",
    "CONFIG_1_3",
    "LHInPlay_1_3",
    "OVInPlay_1_3",
    "Media_l1_Z3",
    "XI_1_3",
    "InPlay_1_3",
)


def _random_uid() -> str:
    return str(random.randint(10**14, 10**15 - 1))


def parse_uid_from_ws_url(url: str) -> str | None:
    """Extract uid=… from a bet365 ZAP WebSocket URL."""
    if "365lpodds" not in url:
        return None
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("uid")
    return values[0] if values else None


def zap_base_url(url: str) -> str:
    """Strip query string; keep trailing slash."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def build_zap_url(base: str, uid: str | None = None) -> str:
    """Append ?uid=… if the base URL has no query string."""
    base = base.rstrip("/") + "/"
    if "uid=" in base:
        return base
    return f"{base}?uid={uid or _random_uid()}"


@dataclass(frozen=True)
class Bet365Config:
    ws_url: str
    ws_aux_url: str
    ws_uid: str | None
    use_aux_socket: bool
    origin: str
    user_agent: str
    cookie: str | None
    session_id: str | None
    nst_token: str | None
    topics: tuple[str, ...]
    sports_config_url: str
    listen_seconds: float
    max_messages: int | None
    output_path: str | None
    use_browser: bool
    browser_cdp_url: str | None
    browser_entry_url: str
    browser_url: str
    browser_timeout_seconds: float
    poll_interval: float
    poll_live_only: bool
    safe_mode: bool
    browser_auto_reload: bool
    browser_initial_attach: bool
    recover_reload: bool
    stale_polls_before_recover: int
    wait_for_cloudflare: bool
    cloudflare_wait_seconds: float
    cloudflare_auto_click: bool
    cloudflare_auto_click_delay_seconds: float
    cookie_banner_auto_click: bool
    cookie_banner_auto_click_delay_seconds: float

    @classmethod
    def from_env(cls) -> "Bet365Config":
        base = os.getenv("BET365_WS_URL", DEFAULT_WS_BASE).strip()
        aux_base = os.getenv("BET365_WS_AUX_URL", DEFAULT_WS_AUX_BASE).strip()
        uid = os.getenv("BET365_WS_UID", "").strip() or None
        cookie = os.getenv("BET365_COOKIE", "").strip() or None
        session_id = os.getenv("BET365_SESSION_ID", "").strip() or None
        nst = os.getenv("BET365_NST_TOKEN", "").strip() or None
        topics_raw = os.getenv("BET365_TOPICS", "").strip()
        topics = tuple(t.strip() for t in topics_raw.split(",") if t.strip()) or DEFAULT_TOPICS
        max_msg_raw = os.getenv("BET365_MAX_MESSAGES", "").strip()
        max_messages = int(max_msg_raw) if max_msg_raw.isdigit() else None
        listen_raw = os.getenv("BET365_LISTEN_SECONDS", "60").strip()
        output = os.getenv("BET365_OUTPUT", "").strip() or None
        cdp_url = os.getenv("BET365_BROWSER_CDP_URL", "").strip() or None
        use_browser_raw = os.getenv("BET365_USE_BROWSER", "false").strip().lower()
        poll_live_raw = os.getenv("BET365_POLL_LIVE_ONLY", "false").strip().lower()
        safe_mode = _env_bool("BET365_SAFE_MODE", True)
        poll_explicit = (
            os.getenv("BET365_POLL_INTERVAL_SECONDS")
            or os.getenv("POLL_INTERVAL_SECONDS")
            or ""
        ).strip()
        if poll_explicit:
            poll_interval = float(poll_explicit)
        elif safe_mode:
            poll_interval = DEFAULT_SAFE_POLL_INTERVAL
        else:
            poll_interval = DEFAULT_POLL_INTERVAL

        browser_auto_reload = _env_bool("BET365_BROWSER_AUTO_RELOAD", not safe_mode)
        browser_initial_attach = _env_bool("BET365_BROWSER_INITIAL_ATTACH", True)
        recover_reload = _env_bool("BET365_RECOVER_RELOAD", not safe_mode)
        stale_default = str(
            DEFAULT_STALE_POLLS_SAFE if safe_mode else DEFAULT_STALE_POLLS
        )
        stale_raw = os.getenv("BET365_STALE_POLLS_BEFORE_RECOVER", stale_default).strip()
        stale_polls_before_recover = (
            int(stale_raw) if stale_raw.isdigit() else int(stale_default)
        )
        cloudflare_wait_raw = os.getenv(
            "BET365_CLOUDFLARE_WAIT_SECONDS",
            str(DEFAULT_CLOUDFLARE_WAIT_SECONDS),
        ).strip()
        auto_click_delay_raw = os.getenv(
            "BET365_CLOUDFLARE_AUTO_CLICK_DELAY_SECONDS",
            str(DEFAULT_CLOUDFLARE_AUTO_CLICK_DELAY),
        ).strip()
        cookie_banner_delay_raw = os.getenv(
            "BET365_COOKIE_BANNER_DELAY_SECONDS",
            str(DEFAULT_COOKIE_BANNER_DELAY_SECONDS),
        ).strip()

        return cls(
            ws_url=build_zap_url(base, uid),
            ws_aux_url=build_zap_url(aux_base, uid),
            ws_uid=uid,
            use_aux_socket=os.getenv("BET365_USE_AUX_SOCKET", "true").lower()
            in ("1", "true", "yes", "on"),
            origin=os.getenv("BET365_ORIGIN", DEFAULT_ORIGIN),
            user_agent=os.getenv("BET365_USER_AGENT", DEFAULT_USER_AGENT),
            cookie=cookie,
            session_id=session_id,
            nst_token=nst,
            topics=topics,
            sports_config_url=os.getenv(
                "BET365_SPORTS_CONFIG_URL",
                "https://www.bet365.com/defaultapi/sports-configuration",
            ),
            listen_seconds=float(listen_raw) if listen_raw else 60.0,
            max_messages=max_messages,
            output_path=output,
            use_browser=use_browser_raw in ("1", "true", "yes", "on"),
            browser_cdp_url=cdp_url or DEFAULT_BROWSER_CDP_URL,
            browser_entry_url=os.getenv(
                "BET365_BROWSER_ENTRY_URL", DEFAULT_BROWSER_ENTRY_URL
            ).strip(),
            browser_url=os.getenv("BET365_BROWSER_URL", DEFAULT_BROWSER_URL),
            browser_timeout_seconds=float(
                os.getenv("BET365_BROWSER_TIMEOUT_SECONDS", str(DEFAULT_BROWSER_TIMEOUT))
            ),
            poll_interval=poll_interval,
            poll_live_only=poll_live_raw in ("1", "true", "yes", "on"),
            safe_mode=safe_mode,
            browser_auto_reload=browser_auto_reload,
            browser_initial_attach=browser_initial_attach,
            recover_reload=recover_reload,
            stale_polls_before_recover=stale_polls_before_recover,
            wait_for_cloudflare=_env_bool("BET365_WAIT_FOR_CLOUDFLARE", True),
            cloudflare_wait_seconds=float(cloudflare_wait_raw)
            if cloudflare_wait_raw
            else DEFAULT_CLOUDFLARE_WAIT_SECONDS,
            cloudflare_auto_click=_env_bool("BET365_CLOUDFLARE_AUTO_CLICK", True),
            cloudflare_auto_click_delay_seconds=float(auto_click_delay_raw)
            if auto_click_delay_raw
            else DEFAULT_CLOUDFLARE_AUTO_CLICK_DELAY,
            cookie_banner_auto_click=_env_bool("BET365_COOKIE_BANNER_AUTO_CLICK", True),
            cookie_banner_auto_click_delay_seconds=float(cookie_banner_delay_raw)
            if cookie_banner_delay_raw
            else DEFAULT_COOKIE_BANNER_DELAY_SECONDS,
        )

    def ws_headers(self) -> list[tuple[str, str]]:
        headers = [
            ("Origin", self.origin),
            ("User-Agent", self.user_agent),
            ("Pragma", "no-cache"),
            ("Cache-Control", "no-cache"),
        ]
        if self.cookie:
            headers.append(("Cookie", self.cookie))
        return headers
