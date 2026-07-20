"""Refresh Liga Stavok / Qrator cookies via Chromium (Playwright)."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.request import urlopen

from ligastavok_live.api import LigastavokApiError, curl_has_session

if TYPE_CHECKING:
    from ligastavok_live.config import LigastavokApiConfig

logger = logging.getLogger(__name__)

_PREFERRED_COOKIE_NAMES: tuple[str, ...] = (
    "qrator_jsid2",
    "qrator_jsr",
    "cfidsgib-w-ligastavok",
    "gsscgib-w-ligastavok",
    "__zzatgib-w-ligastavok",
)

_BLOCK_PAGE_MARKERS: tuple[str, ...] = (
    "заблокирован системой защиты",
    "доступ заблокирован",
    "access blocked",
    "системой защиты",
)

# Welcome / freebet promo overlay ("Фрибет … новым игрокам" → «Получить бонус»).
_PROMO_BUTTON_LABELS: tuple[str, ...] = (
    "Получить бонус",
    "Get bonus",
)
_PROMO_TEXT_MARKERS: tuple[str, ...] = (
    "получить бонус",
    "приветственный бонус",
    "фрибет",
    "новым игрокам",
)

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

_CDP_HELP = """
Qrator blocked Playwright automation (banner: "controlled by automated test software").

Use your normal Chrome instead of Playwright-launched Chromium:

1. Close all Chrome windows.
2. Start Chrome with remote debugging (PowerShell, one line):

   & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" `
     --remote-debugging-port=9222 `
     --user-data-dir="$env:LOCALAPPDATA\\liga-chrome-debug"

3. In that Chrome, open https://www.ligastavok.ru/live and wait until live loads.
4. In backend/.env set:

   LIGASTAVOK_BROWSER_CDP_URL=http://127.0.0.1:9222
   LIGASTAVOK_USE_PLAYWRIGHT=true

5. Run poll again (Playwright will attach to your Chrome, not launch a bot window):

   python main.py poll ligastavok-live --curl capture.curl

Or skip Playwright: refresh capture.curl from DevTools every few minutes.
"""


def build_cookie_header(cookies: list[dict[str, Any]]) -> str:
    """Build a `Cookie` header from Playwright cookie dicts."""
    by_name: dict[str, str] = {}
    for item in cookies:
        domain = (item.get("domain") or "").lower()
        if "ligastavok" not in domain:
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            by_name[str(name)] = str(value)

    parts: list[str] = []
    for name in _PREFERRED_COOKIE_NAMES:
        if name in by_name:
            parts.append(f"{name}={by_name[name]}")
    for name, value in by_name.items():
        if name not in _PREFERRED_COOKIE_NAMES:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _header_has_qrator(header: str) -> bool:
    return bool(header) and "qrator_jsid2" in header


def _cdp_version_url(cdp_url: str) -> str:
    base = cdp_url.rstrip("/")
    if base.endswith("/json"):
        return f"{base}/version"
    return f"{base}/json/version"


def _cdp_is_up(cdp_url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(_cdp_version_url(cdp_url), timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def _wait_for_cdp(cdp_url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _cdp_is_up(cdp_url):
            return True
        time.sleep(0.5)
    return False


def _launch_chrome_cdp_script() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "start_chrome_cdp.ps1"
    if not script.is_file():
        logger.warning("Missing %s — cannot auto-start Chrome", script)
        return
    if sys.platform == "win32":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            check=False,
        )
    else:
        logger.warning("Auto-start Chrome CDP is only implemented for Windows")


class PlaywrightCookieSession:
    """Refresh Qrator cookies via Playwright (CDP attach or persistent profile)."""

    def __init__(self, config: LigastavokApiConfig) -> None:
        self._config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started = False
        self._refresh_count = 0
        self._last_header = ""
        self._cdp_mode = bool(config.browser_cdp_url)
        self._ws_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        self._ws_listener_registered = False
        self._browser_ws_urls: set[str] = set()
        self._ws_bootstrap_attempted = False
        self._promo_dismissed = False

    def start(self) -> None:
        if self._started:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise LigastavokApiError(
                "Playwright is not installed. Run: pip install playwright "
                "&& playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()

        if self._cdp_mode:
            cdp_url = self._config.browser_cdp_url
            assert cdp_url
            if not _cdp_is_up(cdp_url):
                logger.info("CDP not listening — starting Chrome via scripts/start_chrome_cdp.ps1 …")
                _launch_chrome_cdp_script()
                if not _wait_for_cdp(cdp_url, self._config.browser_timeout_seconds):
                    raise LigastavokApiError(
                        f"Chrome CDP still not available at {cdp_url} after "
                        f"{self._config.browser_timeout_seconds:.0f}s.\n\n"
                        "Run in a separate terminal:\n"
                        "  .\\scripts\\start_chrome_cdp.ps1\n"
                        "Wait for 'OK: CDP ready'. Test: http://127.0.0.1:9222/json/version\n"
                        "Then run poll again.\n\n"
                        "If it still fails: Task Manager → end all Google Chrome → run script again."
                    )
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise LigastavokApiError(
                    f"Cannot connect to Chrome at {cdp_url} ({exc}).\n"
                    "Run: .\\scripts\\start_chrome_cdp.ps1\n"
                    "Verify: http://127.0.0.1:9222/json/version shows JSON in a browser."
                ) from exc
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )
            logger.info("Attached to Chrome via CDP: %s", cdp_url)
        elif self._config.browser_profile_dir:
            profile = Path(self._config.browser_profile_dir)
            profile.mkdir(parents=True, exist_ok=True)
            launch_kwargs: dict[str, Any] = {
                "headless": self._config.browser_headless,
                "locale": "ru-RU",
                "viewport": {"width": 1280, "height": 720},
                "ignore_default_args": ["--enable-automation"],
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if self._config.browser_channel:
                launch_kwargs["channel"] = self._config.browser_channel
            else:
                launch_kwargs["user_agent"] = self._config.user_agent

            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile.resolve()),
                **launch_kwargs,
            )
            self._context.add_init_script(_STEALTH_INIT_SCRIPT)
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )
            self._browser = None
            logger.info("Playwright profile: %s", profile.resolve())
        else:
            launch_kwargs = {
                "headless": self._config.browser_headless,
                "ignore_default_args": ["--enable-automation"],
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if self._config.browser_channel:
                launch_kwargs["channel"] = self._config.browser_channel
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            self._context = self._browser.new_context(
                user_agent=self._config.user_agent,
                locale="ru-RU",
                viewport={"width": 1280, "height": 720},
            )
            self._context.add_init_script(_STEALTH_INIT_SCRIPT)
            self._page = self._context.new_page()

        self._started = True
        mode = "cdp" if self._cdp_mode else "launch"
        logger.info("Browser session ready (mode=%s, url=%s)", mode, self._config.browser_url)
        if self._cdp_mode and not self._page_matches_browser_url():
            logger.info(
                "CDP page is %s — navigating to live hub %s",
                getattr(self._page, "url", ""),
                self._config.browser_url,
            )
            try:
                self._load_live_page(force_reload=True)
            except Exception as exc:
                logger.warning("Initial navigate to live hub failed: %s", exc)
        self.ensure_ws_listener()
        self._maybe_dismiss_promo_dialog(wait_for_mount=True)

    @property
    def has_browser_ws(self) -> bool:
        return self._page is not None

    def ensure_ws_listener(self) -> None:
        """Tap WebSocket frames from the real browser (Qrator-safe)."""
        if self._ws_listener_registered or self._page is None:
            return
        self._page.on("websocket", self._on_page_websocket)
        self._ws_listener_registered = True
        logger.info("Listening for browser WebSocket frames")

    def _on_page_websocket(self, ws: Any) -> None:
        url = str(ws.url or "")
        if "ligastavok" not in url.lower() and "/ws" not in url:
            return
        self._browser_ws_urls.add(url)
        if len(self._browser_ws_urls) == 1:
            logger.info("Browser WebSocket connected: %s", url)

        def on_frame(payload: str | bytes) -> None:
            try:
                text = payload if isinstance(payload, str) else payload.decode("utf-8")
                message = json.loads(text)
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return
            if not isinstance(message, dict):
                return
            try:
                self._ws_queue.put_nowait(message)
            except queue.Full:
                pass

        ws.on("framereceived", on_frame)

    def ensure_browser_ws_active(self) -> None:
        """Reload live page once so Playwright can attach to a new WebSocket."""
        self.ensure_ws_listener()
        if self._browser_ws_urls or self._ws_bootstrap_attempted:
            return
        if not self._cdp_mode or self._page is None:
            return
        self._ws_bootstrap_attempted = True
        logger.info(
            "No browser WebSocket yet — reloading %s so score/timer patches can flow",
            self._config.browser_url,
        )
        try:
            self._load_live_page(force_reload=True)
        except Exception as exc:
            logger.warning("Live page reload for WebSocket bootstrap failed: %s", exc)

    def collect_ws_messages(self, deadline: float) -> list[dict[str, Any]]:
        """Drain JSON messages from browser WebSockets until deadline."""
        self.ensure_browser_ws_active()
        messages: list[dict[str, Any]] = []
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                messages.append(self._ws_queue.get(timeout=min(0.25, remaining)))
            except queue.Empty:
                if self._page is not None:
                    self._page.wait_for_timeout(50)
                continue
        return messages

    def _promo_targets(self, page: Any) -> list[Any]:
        targets = [page]
        try:
            for frame in page.frames:
                if frame is not page.main_frame:
                    targets.append(frame)
        except Exception:
            pass
        return targets

    def _is_promo_dialog_visible(self, page: Any) -> bool:
        for target in self._promo_targets(page):
            for label in _PROMO_BUTTON_LABELS:
                try:
                    if target.get_by_role("button", name=label).is_visible(timeout=200):
                        return True
                except Exception:
                    continue
            try:
                body = target.evaluate(
                    "() => (document.body?.innerText || '').slice(0, 4000).toLowerCase()"
                )
                if any(m in body for m in _PROMO_TEXT_MARKERS):
                    # Prefer a visible CTA before treating marker text as enough.
                    for label in _PROMO_BUTTON_LABELS:
                        try:
                            if target.get_by_text(label, exact=False).first.is_visible(
                                timeout=200
                            ):
                                return True
                        except Exception:
                            continue
            except Exception:
                continue
        return False

    def _click_promo_bonus(self, page: Any) -> bool:
        for target in self._promo_targets(page):
            for label in _PROMO_BUTTON_LABELS:
                try:
                    button = target.get_by_role("button", name=label)
                    if not button.is_visible(timeout=500):
                        continue
                    button.click(timeout=2500)
                    logger.info("Promo dialog dismissed (%s)", label)
                    page.wait_for_timeout(300)
                    return True
                except Exception:
                    continue
            for label in _PROMO_BUTTON_LABELS:
                try:
                    button = target.get_by_text(label, exact=False).first
                    if not button.is_visible(timeout=300):
                        continue
                    button.click(timeout=2500)
                    logger.info("Promo dialog dismissed via text (%s)", label)
                    page.wait_for_timeout(300)
                    return True
                except Exception:
                    continue
        return False

    def _maybe_dismiss_promo_dialog(
        self,
        page: Any | None = None,
        *,
        wait_for_mount: bool = False,
    ) -> bool:
        """Click «Получить бонус» on the welcome freebet overlay when present."""
        if not getattr(self._config, "promo_auto_click", True):
            return False
        if self._promo_dismissed:
            return False
        page = page or self._page
        if page is None:
            return False

        delay = float(getattr(self._config, "promo_auto_click_delay_seconds", 1.0) or 0)

        if wait_for_mount:
            deadline = time.monotonic() + max(delay, 0.5) + 3.0
            seen = False
            while time.monotonic() < deadline:
                if self._is_promo_dialog_visible(page):
                    seen = True
                    break
                try:
                    page.wait_for_timeout(250)
                except Exception:
                    time.sleep(0.25)
            if not seen:
                return False
            if delay > 0:
                try:
                    page.wait_for_timeout(int(delay * 1000))
                except Exception:
                    time.sleep(delay)
        elif not self._is_promo_dialog_visible(page):
            return False

        if self._click_promo_bonus(page):
            self._promo_dismissed = True
            print("Liga Stavok promo: clicked Get bonus button.")
            return True
        return False

    def _page_matches_browser_url(self) -> bool:
        page = self._page
        if page is None:
            return False
        current = (page.url or "").split("?", 1)[0].rstrip("/").lower()
        target = self._config.browser_url.split("?", 1)[0].rstrip("/").lower()
        return current == target

    def _navigate_live(self, page: Any, url: str, timeout_ms: int) -> None:
        current = (page.url or "").split("?", 1)[0].rstrip("/")
        target = url.split("?", 1)[0].rstrip("/")
        if current == target:
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        else:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        self._promo_dismissed = False
        self._maybe_dismiss_promo_dialog(page, wait_for_mount=True)

    def _raise_if_blocked(self) -> None:
        page = self._page
        try:
            text = (page.inner_text("body") or "").lower()
        except Exception:
            return
        if any(marker in text for marker in _BLOCK_PAGE_MARKERS):
            raise LigastavokApiError(
                "Liga Stavok Qrator block page detected "
                '("Доступ заблокирован системой защиты"). '
                + _CDP_HELP
            )

    def _cookies_from_context(self) -> str:
        return build_cookie_header(self._context.cookies())

    def _wait_for_session_cookies(self) -> str:
        page = self._page
        deadline = time.monotonic() + self._config.browser_timeout_seconds
        last_header = ""

        while time.monotonic() < deadline:
            self._raise_if_blocked()
            header = self._cookies_from_context()
            last_header = header
            if _header_has_qrator(header):
                return header
            page.wait_for_timeout(500)

        if _header_has_qrator(last_header):
            return last_header

        raise LigastavokApiError(
            "No qrator_jsid2 cookie obtained."
            + (_CDP_HELP if not self._cdp_mode else "")
        )

    def _load_live_page(self, *, force_reload: bool = False) -> None:
        # CDP shortcut: cookies alone are not enough — must already be on /live.
        if self._cdp_mode and not force_reload:
            header = self._cookies_from_context()
            if _header_has_qrator(header) and self._page_matches_browser_url():
                return

        page = self._page
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)

        def _is_events_list(response: Any) -> bool:
            return "eventsList" in response.url and response.status == 200

        urls = [self._config.browser_url]

        last_exc: Exception | None = None
        for url in urls:
            try:
                with page.expect_response(_is_events_list, timeout=min(timeout_ms, 25_000)):
                    self._navigate_live(page, url, timeout_ms)
                self._raise_if_blocked()
                return
            except LigastavokApiError:
                raise
            except Exception as exc:
                last_exc = exc
                logger.debug("Page load %s: %s", url, exc)

        if last_exc:
            logger.warning(
                "eventsList not seen during page load (%s); polling cookies…",
                last_exc,
            )
        page.goto(urls[0], wait_until="domcontentloaded", timeout=timeout_ms)
        self._raise_if_blocked()

    def refresh_cookie_header(self, *, force_reload: bool = False) -> str:
        if not self._started:
            self.start()

        if self._cdp_mode and not force_reload:
            header = self._cookies_from_context()
            if _header_has_qrator(header) and self._page_matches_browser_url():
                self._maybe_dismiss_promo_dialog()
                if header != self._last_header:
                    logger.info("CDP: cookies from open Chrome (%s chars)", len(header))
                self._last_header = header
                self._refresh_count += 1
                return header

        self._load_live_page(force_reload=force_reload)
        header = self._wait_for_session_cookies()
        self._maybe_dismiss_promo_dialog(wait_for_mount=True)
        self._refresh_count += 1
        self._last_header = header
        logger.info("Browser page reload — cookies updated (%s chars)", len(header))
        return header

    def close(self) -> None:
        if self._cdp_mode:
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
            self._browser = None
            self._context = None
            self._page = None
        else:
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
            self._context = None
            self._browser = None
            self._page = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._started = False

    def __enter__(self) -> PlaywrightCookieSession:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
