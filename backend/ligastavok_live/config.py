import os
from dataclasses import dataclass
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

DEFAULT_WS_URL = "wss://lds-api-sites.ligastavok.ru/ws"
DEFAULT_WS_SUBSCRIBE_METHOD = "/notifications/v3/eventUpdated"
DEFAULT_SNAPSHOT_URL = "https://lds-api-sites.ligastavok.ru/rest/events/v8/eventsList"
DEFAULT_POLL_INTERVAL = 3.5
DEFAULT_SNAPSHOT_LIMIT = 160
DEFAULT_SNAPSHOT_MAX_PAGES = 0  # 0 = fetch until API total reached
DEFAULT_SNAPSHOT_PARALLEL_WORKERS = 6
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


DEFAULT_BROWSER_URL = "https://www.ligastavok.ru/live"
LIVE_BROWSER_URL = "https://www.ligastavok.ru/live"
DEFAULT_BROWSER_TIMEOUT = 90.0
DEFAULT_BROWSER_REFRESH_EVERY = 12
DEFAULT_BROWSER_REFRESH_MIN = 12
DEFAULT_BROWSER_REFRESH_MAX = 16


def _normalize_live_browser_url(url: str | None) -> str:
    """Live hub must be https://www.ligastavok.ru/live — never the bare site root."""
    raw = (url or "").strip()
    path = raw.split("?", 1)[0].rstrip("/").lower()
    if path.endswith("/live"):
        return raw.split("?", 1)[0].rstrip("/")
    return LIVE_BROWSER_URL


def _parse_browser_refresh() -> tuple[int | None, int | None, int]:
    """Return (min, max, fixed_every). min/max set => random interval each cycle."""
    every_raw = os.getenv("LIGASTAVOK_BROWSER_REFRESH_EVERY", "").strip()
    range_raw = os.getenv("LIGASTAVOK_BROWSER_REFRESH_RANGE", "").strip()

    if every_raw:
        fixed = max(1, int(every_raw))
        return None, None, fixed

    if range_raw and "-" in range_raw:
        lo_s, hi_s = range_raw.split("-", 1)
        lo = max(1, int(lo_s.strip()))
        hi = max(lo, int(hi_s.strip()))
        return lo, hi, lo

    if not range_raw and not every_raw:
        return DEFAULT_BROWSER_REFRESH_MIN, DEFAULT_BROWSER_REFRESH_MAX, DEFAULT_BROWSER_REFRESH_EVERY

    if range_raw.isdigit():
        fixed = max(1, int(range_raw))
        return None, None, fixed

    return DEFAULT_BROWSER_REFRESH_MIN, DEFAULT_BROWSER_REFRESH_MAX, DEFAULT_BROWSER_REFRESH_EVERY


@dataclass(frozen=True)
class LigastavokApiConfig:
    ws_url: str
    ws_subscribe_method: str
    snapshot_url: str
    poll_interval: float
    ws_timeout: float
    http_timeout: float
    application_name: str
    user_agent: str
    cookie: str | None
    snapshot_body: str | None
    curl_file: str | None
    snapshot_limit: int
    snapshot_max_pages: int
    live_all_sports: bool
    snapshot_ns: str
    extra_headers: dict[str, str]
    use_playwright: bool
    browser_headless: bool
    browser_url: str
    browser_timeout_seconds: float
    browser_refresh_every: int
    browser_refresh_min: int | None
    browser_refresh_max: int | None
    browser_profile_dir: str | None
    browser_cdp_url: str | None
    browser_channel: str | None
    promo_auto_click: bool
    promo_auto_click_delay_seconds: float
    snapshot_parallel_pages: bool
    snapshot_parallel_workers: int
    json_pretty: bool
    profile: bool
    ws_enabled: bool

    @classmethod
    def from_env(cls) -> "LigastavokApiConfig":
        cookie = os.getenv("LIGASTAVOK_COOKIE", "").strip() or None
        snapshot_body = os.getenv("LIGASTAVOK_SNAPSHOT_BODY", "").strip() or None
        curl_file = os.getenv("LIGASTAVOK_CURL_FILE", "").strip() or None
        profile_dir = os.getenv("LIGASTAVOK_BROWSER_PROFILE_DIR", "").strip() or None
        cdp_url = os.getenv("LIGASTAVOK_BROWSER_CDP_URL", "").strip() or None
        channel = os.getenv("LIGASTAVOK_BROWSER_CHANNEL", "").strip() or None
        live_all_raw = os.getenv("LIGASTAVOK_LIVE_ALL_SPORTS", "true").strip().lower()
        snapshot_ns = os.getenv("LIGASTAVOK_NS", "live").strip().lower() or "live"
        if snapshot_ns not in ("live", "prematch"):
            snapshot_ns = "live"
        playwright_raw = os.getenv("LIGASTAVOK_USE_PLAYWRIGHT", "true").strip().lower()
        headless_raw = os.getenv("LIGASTAVOK_BROWSER_HEADLESS", "false").strip().lower()
        promo_raw = os.getenv("LIGASTAVOK_PROMO_AUTO_CLICK", "true").strip().lower()
        promo_delay_raw = os.getenv(
            "LIGASTAVOK_PROMO_AUTO_CLICK_DELAY_SECONDS", "1"
        ).strip()
        parallel_raw = os.getenv("LIGASTAVOK_SNAPSHOT_PARALLEL", "true").strip().lower()
        json_pretty_raw = os.getenv("LIGASTAVOK_JSON_PRETTY", "false").strip().lower()
        profile_raw = os.getenv("LIGASTAVOK_PROFILE", "false").strip().lower()
        ws_enabled_raw = os.getenv("LIGASTAVOK_WS_ENABLED", "true").strip().lower()
        extra: dict[str, str] = {}
        raw = os.getenv("LIGASTAVOK_EXTRA_HEADERS", "").strip()
        if raw:
            for part in raw.split(";"):
                if ":" in part:
                    key, value = part.split(":", 1)
                    extra[key.strip()] = value.strip()

        refresh_min, refresh_max, refresh_every = _parse_browser_refresh()

        browser_url = os.getenv("LIGASTAVOK_BROWSER_URL", DEFAULT_BROWSER_URL)
        if snapshot_ns == "live":
            browser_url = _normalize_live_browser_url(browser_url)

        return cls(
            ws_url=os.getenv("LIGASTAVOK_WS_URL", DEFAULT_WS_URL),
            ws_subscribe_method=os.getenv(
                "LIGASTAVOK_WS_SUBSCRIBE_METHOD", DEFAULT_WS_SUBSCRIBE_METHOD
            ),
            snapshot_url=os.getenv("LIGASTAVOK_SNAPSHOT_URL", DEFAULT_SNAPSHOT_URL),
            poll_interval=float(
                os.getenv("LIGASTAVOK_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL))
            ),
            ws_timeout=float(os.getenv("LIGASTAVOK_WS_TIMEOUT", "30")),
            http_timeout=float(os.getenv("LIGASTAVOK_HTTP_TIMEOUT", "30")),
            application_name=os.getenv("LIGASTAVOK_APP_NAME", "mobile"),
            user_agent=os.getenv("LIGASTAVOK_USER_AGENT", DEFAULT_USER_AGENT),
            cookie=cookie,
            snapshot_body=snapshot_body,
            curl_file=curl_file,
            snapshot_limit=int(os.getenv("LIGASTAVOK_SNAPSHOT_LIMIT", str(DEFAULT_SNAPSHOT_LIMIT))),
            snapshot_max_pages=int(
                os.getenv("LIGASTAVOK_SNAPSHOT_MAX_PAGES", str(DEFAULT_SNAPSHOT_MAX_PAGES))
            ),
            live_all_sports=live_all_raw in ("1", "true", "yes", "on"),
            snapshot_ns=snapshot_ns,
            extra_headers=extra,
            use_playwright=playwright_raw in ("1", "true", "yes", "on"),
            browser_headless=headless_raw in ("1", "true", "yes", "on"),
            browser_url=browser_url,
            browser_timeout_seconds=float(
                os.getenv("LIGASTAVOK_BROWSER_TIMEOUT_SECONDS", str(DEFAULT_BROWSER_TIMEOUT))
            ),
            browser_refresh_every=refresh_every,
            browser_refresh_min=refresh_min,
            browser_refresh_max=refresh_max,
            browser_profile_dir=profile_dir,
            browser_cdp_url=cdp_url,
            browser_channel=channel,
            promo_auto_click=promo_raw in ("1", "true", "yes", "on"),
            promo_auto_click_delay_seconds=float(promo_delay_raw or "1"),
            snapshot_parallel_pages=parallel_raw in ("1", "true", "yes", "on"),
            snapshot_parallel_workers=int(
                os.getenv(
                    "LIGASTAVOK_SNAPSHOT_PARALLEL_WORKERS",
                    str(DEFAULT_SNAPSHOT_PARALLEL_WORKERS),
                )
            ),
            json_pretty=json_pretty_raw in ("1", "true", "yes", "on"),
            profile=profile_raw in ("1", "true", "yes", "on"),
            ws_enabled=ws_enabled_raw in ("1", "true", "yes", "on"),
        )

    def snapshot_query(
        self,
        *,
        ns: str = "live",
        game_id: int | None = None,
        limit: int = 40,
        skip: int = 0,
    ) -> str:
        params: dict[str, str | int] = {"ns": ns, "limit": limit, "skip": skip}
        if game_id is not None:
            params["gameId"] = game_id
        return f"{self.snapshot_url}?{urlencode(params)}"

    def request_headers(self) -> dict[str, str]:
        if self.snapshot_ns == "prematch":
            referer = "https://www.ligastavok.ru/"
        else:
            referer = "https://www.ligastavok.ru/live"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.user_agent,
            "Origin": "https://www.ligastavok.ru",
            "Referer": referer,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        headers.update(self.extra_headers)
        return headers

DEFAULT_SITE_NAME = "ligastavok.ru"


def live_prune_absent_from_env() -> bool:
    """When true, delete place=live rows absent from a full HTTP snapshot."""
    raw = os.getenv("LIGASTAVOK_LIVE_PRUNE_ABSENT", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def live_prune_min_fixtures_from_env() -> int:
    """Refuse prune if the HTTP snapshot exported fewer fixtures than this."""
    return max(1, int(os.getenv("LIGASTAVOK_LIVE_PRUNE_MIN_FIXTURES", "1") or "1"))


def live_config_from_env() -> LigastavokApiConfig:
    """Build config aimed at https://www.ligastavok.ru/live."""
    from dataclasses import replace

    base = LigastavokApiConfig.from_env()
    browser_url = _normalize_live_browser_url(
        os.getenv("LIGASTAVOK_LIVE_BROWSER_URL", "").strip()
        or base.browser_url
        or DEFAULT_BROWSER_URL
    )
    cdp = (
        os.getenv("LIGASTAVOK_LIVE_BROWSER_CDP_URL", "").strip()
        or base.browser_cdp_url
    )
    return replace(
        base,
        snapshot_ns="live",
        browser_url=browser_url,
        browser_cdp_url=cdp,
    )

