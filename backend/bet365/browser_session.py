"""Capture Bet365 WebSocket uid + cookies via CDP Chrome (Liga Stavok-style)."""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from bet365.cloudflare_gate import (
    attempt_turnstile_click,
    challenge_user_message,
    is_bet365_authenticated,
    is_bet365_live_ready,
    is_cloudflare_challenge,
    is_live_hub_url,
)
from bet365.config import (
    Bet365Config,
    build_zap_url,
    parse_uid_from_ws_url,
    zap_base_url,
)

logger = logging.getLogger(__name__)

_PREFERRED_COOKIE_NAMES: tuple[str, ...] = (
    "pstk",
    "aps03",
    "session",
    "swt",
)

# Cookie consent banner (fresh bet365-chrome-debug profile)
_COOKIE_ACCEPT_LABELS: tuple[str, ...] = (
    "Accept All",
    "Essential Only",
    "Accept all",
)


class Bet365BrowserError(RuntimeError):
    pass


@dataclass
class CapturedSession:
    uid: str | None
    cookie: str
    session_id: str | None
    premws_url: str | None
    aux_url: str | None
    ws_urls: tuple[str, ...]


def build_cookie_header(cookies: list[dict[str, Any]]) -> str:
    by_name: dict[str, str] = {}
    for item in cookies:
        domain = (item.get("domain") or "").lower()
        if "bet365" not in domain:
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


def _launch_chrome_script() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "start_chrome_cdp_bet365.ps1"
    if not script.is_file():
        logger.warning("Missing %s", script)
        return
    if sys.platform == "win32":
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            check=False,
        )


class Bet365BrowserSession:
    """Attach to real Chrome via CDP; capture ZAP uid from WebSocket URLs."""

    def __init__(self, config: Bet365Config) -> None:
        self._config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._ws_urls: set[str] = set()
        self._uid: str | None = None
        self._premws_base: str | None = None
        self._aux_base: str | None = None
        self._frame_queue: queue.Queue[str] = queue.Queue(maxsize=5000)
        self._listener_registered = False
        self._context_listener_registered = False
        self._registered_page_ids: set[int] = set()
        self._bootstrap_attach_done = False
        self._cloudflare_waiting = False
        self._cloudflare_challenge_since: float | None = None
        self._cloudflare_auto_click_done = False
        self._live_hub_opened = False
        self._cloudflare_notice_printed = False
        self._cloudflare_auto_click_attempts = 0

    def _has_cf_clearance_cookie(self) -> bool:
        if self._context is None:
            return False
        for item in self._context.cookies():
            name = str(item.get("name") or "").lower()
            if name == "cf_clearance":
                domain = str(item.get("domain") or "").lower()
                if "bet365" in domain or domain.startswith("."):
                    return True
        return False

    def _reset_cloudflare_episode(self) -> None:
        self._cloudflare_challenge_since = None
        self._cloudflare_auto_click_done = False
        self._cloudflare_notice_printed = False
        self._cloudflare_auto_click_attempts = 0

    def _maybe_auto_click_cloudflare(self) -> None:
        if not self._config.cloudflare_auto_click or self._page is None:
            return
        if self._cloudflare_challenge_since is None:
            return

        elapsed = time.monotonic() - self._cloudflare_challenge_since
        delay = self._config.cloudflare_auto_click_delay_seconds
        if elapsed < delay:
            return

        # Retry auto-click every delay period (max 5 attempts per episode).
        attempt_slot = int(elapsed // delay)
        if attempt_slot <= self._cloudflare_auto_click_attempts:
            return
        if self._cloudflare_auto_click_attempts >= 5:
            return

        self._cloudflare_auto_click_attempts += 1
        print(
            f"Auto-clicking Cloudflare checkbox "
            f"(attempt {self._cloudflare_auto_click_attempts}, {delay:.0f}s delay) …"
        )
        if attempt_turnstile_click(self._page):
            logger.info(
                "Cloudflare auto-click attempt %s succeeded",
                self._cloudflare_auto_click_attempts,
            )
            print("Cloudflare checkbox clicked — waiting for verification …")
            self._page.wait_for_timeout(3000)
        else:
            logger.warning(
                "Cloudflare auto-click attempt %s failed — click manually in CDP Chrome",
                self._cloudflare_auto_click_attempts,
            )
            print("Auto-click missed — please click \"Verify you are human\" in CDP Chrome.")

    def _has_pstk_cookie(self) -> bool:
        cookie = self._cookie_header()
        return self._session_id_from_cookie(cookie) is not None

    def _read_page_state(self) -> tuple[str, str, str]:
        page = self._page
        if page is None:
            return "", "", ""
        url = page.url or ""
        try:
            title = page.title() or ""
        except Exception:
            title = ""
        body_text = ""
        try:
            body_text = page.evaluate(
                "() => (document.body?.innerText || '').slice(0, 4000)"
            )
        except Exception:
            body_text = ""
        return url, title, body_text

    def _open_entry_page(self) -> None:
        """Load bet365 root for Cloudflare auth (not the live hub)."""
        page = self._page
        if page is None:
            return
        entry = self._config.browser_entry_url.rstrip("/") + "/"
        current = (page.url or "").split("#", 1)[0].rstrip("/") + "/"
        if current.rstrip("/") == entry.rstrip("/") and not is_live_hub_url(page.url or ""):
            return
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)
        logger.info("Opening entry page %s for Cloudflare authentication …", entry)
        print(f"Opening {entry} for Cloudflare authentication …")
        page.goto(entry, wait_until="domcontentloaded", timeout=timeout_ms)

    def _navigate_to_live_hub(self, *, reload_if_on_page: bool = False) -> None:
        """Open live hub after authentication."""
        page = self._page
        if page is None:
            return
        live = self._config.browser_url
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)
        current_url = page.url or ""

        if is_live_hub_url(current_url):
            if reload_if_on_page:
                logger.info("Reloading live hub %s …", live)
                page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            else:
                return
        else:
            logger.info("Authentication OK — opening live hub %s", live)
            print(f"Cloudflare passed — opening live hub {live}")
            page.goto(live, wait_until="domcontentloaded", timeout=timeout_ms)

        self._live_hub_opened = True
        self._dismiss_cookie_banner(page)

    def _wait_for_authentication(self, deadline: float) -> None:
        """Wait on entry URL until Cloudflare is cleared."""
        last_countdown = 0.0

        while time.monotonic() < deadline:
            url, title, body_text = self._read_page_state()
            if is_bet365_authenticated(
                url=url,
                title=title,
                body_text=body_text,
                has_pstk=self._has_pstk_cookie(),
                has_cf_clearance=self._has_cf_clearance_cookie(),
            ):
                print("Cloudflare verification complete — continuing.")
                return

            if is_cloudflare_challenge(url=url, title=title, body_text=body_text):
                if self._cloudflare_challenge_since is None:
                    self._cloudflare_challenge_since = time.monotonic()
                    self._cloudflare_auto_click_attempts = 0
                    self._cloudflare_notice_printed = False

                if not self._cloudflare_notice_printed:
                    self._cloudflare_notice_printed = True
                    self._cloudflare_waiting = True
                    auto_delay = (
                        self._config.cloudflare_auto_click_delay_seconds
                        if self._config.cloudflare_auto_click
                        else None
                    )
                    message = challenge_user_message(
                        self._config.browser_entry_url,
                        self._config.browser_url,
                        auto_click_delay=auto_delay,
                    )
                    logger.warning(message.replace("\n", " "))
                    print(f"\n{message}\n")

                self._maybe_auto_click_cloudflare()

                if self._config.cloudflare_auto_click and self._cloudflare_challenge_since:
                    elapsed = time.monotonic() - self._cloudflare_challenge_since
                    delay = self._config.cloudflare_auto_click_delay_seconds
                    remaining = max(0, delay - elapsed)
                    now = time.monotonic()
                    if remaining > 0 and now - last_countdown >= 5.0:
                        print(f"Waiting for Cloudflare … auto-click in {remaining:.0f}s")
                        last_countdown = now
            else:
                now = time.monotonic()
                if now - last_countdown >= 10.0:
                    logger.info("Loading bet365 entry page … url=%s title=%r", url[:80], title)
                    last_countdown = now

            self._page.wait_for_timeout(1000)

        url, title, _body = self._read_page_state()
        raise Bet365BrowserError(
            "Timed out waiting for Cloudflare verification on entry page.\n"
            f"{challenge_user_message(self._config.browser_entry_url, self._config.browser_url)}\n"
            f"Last page: {title!r} {url[:160]}"
        )

    def ensure_bet365_ready(self, *, timeout: float | None = None) -> None:
        """Entry URL auth → live hub → ready for ZAP."""
        if not self._config.wait_for_cloudflare or self._page is None:
            return

        wait_seconds = (
            timeout if timeout is not None else self._config.cloudflare_wait_seconds
        )
        auth_deadline = time.monotonic() + wait_seconds

        self._open_entry_page()
        self._wait_for_authentication(auth_deadline)
        self._reset_cloudflare_episode()
        self._cloudflare_waiting = False

        self._navigate_to_live_hub()

        live_deadline = time.monotonic() + min(60.0, max(0.0, auth_deadline - time.monotonic()))
        while time.monotonic() < live_deadline:
            url, title, body_text = self._read_page_state()
            if is_bet365_live_ready(
                url=url,
                title=title,
                body_text=body_text,
                has_pstk=self._has_pstk_cookie(),
                has_zap_socket=bool(self._ws_urls),
            ):
                logger.info("Live hub ready at %s", url[:120])
                return
            if is_cloudflare_challenge(url=url, title=title, body_text=body_text):
                logger.warning("Cloudflare reappeared — returning to entry page …")
                self._open_entry_page()
                self._wait_for_authentication(auth_deadline)
                self._navigate_to_live_hub()
            self._page.wait_for_timeout(1000)

        url, title, body_text = self._read_page_state()
        if is_bet365_authenticated(
            url=url,
            title=title,
            body_text=body_text,
            has_pstk=self._has_pstk_cookie(),
            has_cf_clearance=self._has_cf_clearance_cookie(),
        ):
            logger.info("Live hub loaded; waiting for ZAP socket during bootstrap")
            return

        raise Bet365BrowserError(
            "Timed out waiting for bet365 live hub after authentication.\n"
            f"Expected: {self._config.browser_url}\n"
            f"Last page: {title!r} {url[:160]}"
        )

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise Bet365BrowserError(
                "Playwright required. Run: pip install playwright && playwright install chromium"
            ) from exc

        cdp_url = self._config.browser_cdp_url
        if not cdp_url:
            raise Bet365BrowserError("Set BET365_BROWSER_CDP_URL=http://127.0.0.1:9223")

        self._playwright = sync_playwright().start()

        if not _cdp_is_up(cdp_url):
            logger.info("CDP not up — starting Chrome via start_chrome_cdp_bet365.ps1 …")
            _launch_chrome_script()
            if not _wait_for_cdp(cdp_url, self._config.browser_timeout_seconds):
                raise Bet365BrowserError(
                    f"Chrome CDP not available at {cdp_url}.\n"
                    "Run: .\\scripts\\start_chrome_cdp_bet365.ps1\n"
                    "Open bet365.com in that Chrome window, then retry."
                )

        try:
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise Bet365BrowserError(f"Cannot connect to Chrome at {cdp_url}: {exc}") from exc

        self._context = (
            self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._ensure_ws_listener()
        logger.info(
            "Attached to Chrome CDP: %s (page: %s)",
            cdp_url,
            self._page.url or "(blank)",
        )
        self.ensure_bet365_ready()

    def _register_page_listener(self, page: Any) -> None:
        page_id = id(page)
        if page_id in self._registered_page_ids:
            return
        page.on("websocket", self._on_websocket)
        self._registered_page_ids.add(page_id)
        logger.debug("WebSocket listener on tab: %s", page.url or "(blank)")

    def _on_new_page(self, page: Any) -> None:
        self._register_page_listener(page)

    def _ensure_ws_listener(self) -> None:
        if self._context is None:
            return
        for page in self._context.pages:
            self._register_page_listener(page)
        if not self._context_listener_registered:
            self._context.on("page", self._on_new_page)
            self._context_listener_registered = True
        if not self._listener_registered:
            self._listener_registered = True
            logger.info("Listening for bet365 WebSocket connections (365lpodds.com)")

    def _on_websocket(self, ws: Any) -> None:
        url = str(ws.url or "")
        if "365lpodds" not in url or "/zap/" not in url:
            return

        self._ws_urls.add(url)
        uid = parse_uid_from_ws_url(url)
        if uid and not self._uid:
            self._uid = uid
            logger.info("Captured uid=%s from browser WebSocket", uid)

        base = zap_base_url(url)
        if "premws" in url and not self._premws_base:
            self._premws_base = base
            logger.info("Main ZAP socket: %s", url)
        if "pshudws" in url and not self._aux_base:
            self._aux_base = base
            logger.info("Aux ZAP socket: %s", url)

        def on_frame(payload: str | bytes) -> None:
            try:
                text = payload if isinstance(payload, str) else payload.decode("utf-8", errors="replace")
                self._frame_queue.put_nowait(text)
            except queue.Full:
                pass

        ws.on("framereceived", on_frame)

    def _cookie_header(self) -> str:
        return build_cookie_header(self._context.cookies())

    def _session_id_from_cookie(self, cookie: str) -> str | None:
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("pstk="):
                return part.split("=", 1)[1]
        return None

    def _dismiss_cookie_banner(self, page: Any) -> bool:
        """Click bet365 cookie consent if visible (blocks ZAP on fresh profiles)."""
        page.wait_for_timeout(400)
        for label in _COOKIE_ACCEPT_LABELS:
            try:
                page.get_by_role("button", name=label).click(timeout=2500)
                logger.info("Cookie banner dismissed (%s)", label)
                page.wait_for_timeout(300)
                return True
            except Exception:
                continue
        return False

    def _navigate_live(self, page: Any, url: str, timeout_ms: int) -> None:
        """Reload live hub so Playwright sees a fresh WebSocket."""
        current = (page.url or "").split("?", 1)[0].rstrip("/")
        target = url.split("?", 1)[0].rstrip("/")
        if current == target and is_live_hub_url(page.url or ""):
            logger.info("Reloading %s to attach ZAP WebSocket …", url)
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        else:
            logger.info("Opening %s …", url)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        self._dismiss_cookie_banner(page)

    def _reload_if_needed(self) -> None:
        if not self._config.browser_auto_reload:
            return
        if self._uid:
            return
        page = self._page
        if page is None:
            return
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)
        self._navigate_live(page, self._config.browser_url, timeout_ms)

    def _maybe_initial_attach(self) -> None:
        """One navigate/reload on live hub so Playwright can attach to ZAP."""
        if self._bootstrap_attach_done or not self._config.browser_initial_attach:
            return
        if self._ws_urls:
            self._bootstrap_attach_done = True
            return
        if self._page is None:
            return
        self._navigate_to_live_hub(reload_if_on_page=True)
        self._bootstrap_attach_done = True

    def _wait_for_zap_socket(self, timeout: float) -> bool:
        """Wait until premws/pshudws connects (Playwright must see it)."""
        if self._page is None:
            self.start()

        self._ensure_ws_listener()
        deadline = time.monotonic() + timeout
        retry_reload_done = False
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)

        if not self._ws_urls:
            if self._config.browser_auto_reload:
                self._navigate_live(self._page, self._config.browser_url, timeout_ms)
            else:
                self._maybe_initial_attach()

        while time.monotonic() < deadline:
            if self._ws_urls:
                return True
            if (
                self._config.browser_auto_reload
                and not retry_reload_done
                and time.monotonic() > deadline - timeout / 2
            ):
                retry_reload_done = True
                logger.info("No ZAP socket yet — reloading again …")
                try:
                    self._navigate_live(self._page, self._config.browser_url, timeout_ms)
                except Exception as exc:
                    logger.warning("Reload failed: %s", exc)
            self._page.wait_for_timeout(500)

        if not self._ws_urls and not self._config.browser_auto_reload:
            logger.warning(
                "No ZAP WebSocket captured. Load %s in CDP Chrome and press F5 once, "
                "then restart poll (safe mode — no further auto reload).",
                self._config.browser_url,
            )
        return bool(self._ws_urls)

    def capture(self, *, wait_seconds: float | None = None) -> CapturedSession:
        """Wait until uid + pstk cookie are seen (or timeout)."""
        if self._page is None:
            self.start()

        timeout = (
            wait_seconds
            if wait_seconds is not None
            else self._config.browser_timeout_seconds
        )
        deadline = time.monotonic() + timeout
        retry_reload_done = False

        if self._config.browser_auto_reload:
            self._reload_if_needed()
        else:
            self._maybe_initial_attach()

        while time.monotonic() < deadline:
            cookie = self._cookie_header()
            session_id = self._session_id_from_cookie(cookie)
            if self._uid and session_id:
                break
            if (
                self._config.browser_auto_reload
                and not self._uid
                and not retry_reload_done
                and time.monotonic() > deadline - timeout / 2
            ):
                retry_reload_done = True
                self._reload_if_needed()
            self._page.wait_for_timeout(500)

        cookie = self._cookie_header()
        session_id = self._session_id_from_cookie(cookie)

        if not self._uid:
            raise Bet365BrowserError(
                "No uid captured from browser WebSocket.\n"
                "Ensure bet365.com live line is loaded in the CDP Chrome window."
            )
        if not session_id:
            raise Bet365BrowserError(
                "No pstk cookie — log in / load bet365.com in the CDP Chrome window."
            )

        premws = build_zap_url(
            self._premws_base or self._config.ws_url.split("?")[0],
            self._uid,
        )
        aux_base = self._aux_base or self._config.ws_aux_url.split("?")[0]
        aux = build_zap_url(aux_base, self._uid)

        return CapturedSession(
            uid=self._uid,
            cookie=cookie,
            session_id=session_id,
            premws_url=premws,
            aux_url=aux,
            ws_urls=tuple(sorted(self._ws_urls)),
        )

    def bootstrap_websocket_tap(self) -> None:
        """Attach to ZAP WebSockets in CDP Chrome (one initial navigate in safe mode)."""
        if self._page is None:
            self.start()
        else:
            self.ensure_bet365_ready()
        self._wait_for_zap_socket(min(self._config.browser_timeout_seconds, 45.0))

    def recover_feed_once(self) -> bool:
        """Explicit recovery after stale feed — at most one reload when enabled."""
        if not self._config.recover_reload:
            logger.warning(
                "Feed stale (%s empty poll(s)) — reload %s manually in CDP Chrome "
                "(BET365_RECOVER_RELOAD=false).",
                self._config.stale_polls_before_recover,
                self._config.browser_url,
            )
            return False

        page = self._page
        if page is None:
            return False

        logger.warning(
            "Feed stale (%s empty poll(s)) — one recovery reload …",
            self._config.stale_polls_before_recover,
        )
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)
        try:
            self._navigate_live(page, self._config.browser_url, timeout_ms)
        except Exception as exc:
            logger.warning("Recovery reload failed: %s", exc)
            return False

        deadline = time.monotonic() + min(self._config.browser_timeout_seconds, 20.0)
        while time.monotonic() < deadline:
            if not self._frame_queue.empty() or self._ws_urls:
                logger.info("Feed recovered after reload")
                return True
            page.wait_for_timeout(500)

        logger.warning("Recovery reload finished but no ZAP frames yet")
        return False

    def listen(
        self,
        *,
        duration: float | None = None,
        max_messages: int | None = None,
        output: Path | None = None,
        parse_odds: bool = False,
        live_only: bool = False,
        verbose: bool = True,
    ) -> int:
        """Tap ZAP frames from the browser (no Python WebSocket connect)."""
        from bet365.mapper import print_odds_snapshot, state_summary
        from bet365.protocol import (
            TYPE_DELTA,
            TYPE_TOPIC_LOAD,
            frame_summary,
            parse_frame,
            split_frames,
        )
        from bet365.state import ZapFeedState

        if self._page is None:
            self.start()
        self.bootstrap_websocket_tap()

        timeout = duration if duration is not None else self._config.listen_seconds
        deadline = time.time() + timeout
        limit = max_messages if max_messages is not None else self._config.max_messages
        out_path = output or (Path(self._config.output_path) if self._config.output_path else None)

        received = 0
        records: list[dict[str, Any]] = []
        uid_logged = False
        feed = ZapFeedState() if parse_odds else None

        while time.time() < deadline:
            if limit is not None and received >= limit:
                break
            if self._uid and not uid_logged:
                logger.info("Tapping uid=%s (%s socket(s))", self._uid, len(self._ws_urls))
                uid_logged = True
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                raw = self._frame_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if self._page is not None:
                    try:
                        self._page.wait_for_timeout(50)
                    except Exception as exc:
                        if "closed" in str(exc).lower():
                            logger.info("Browser closed — stopping listen (%s frames so far)", received)
                            break
                        raise
                continue

            for part in split_frames(raw):
                if feed is not None:
                    feed.apply_chunk(part)
                frame = parse_frame(part)
                received += 1
                summary = frame_summary(frame)
                if out_path is not None or verbose:
                    records.append({"ts": time.time(), **summary})
                if verbose and not parse_odds:
                    kind = frame.frame_type or "?"
                    print(
                        f"[{received}] type={kind!r} topic={summary.get('topic')!r} "
                        f"len={summary['body_len']}"
                    )
                    if frame.frame_type in (TYPE_TOPIC_LOAD, TYPE_DELTA) and summary["preview"]:
                        print(f"  preview: {summary['preview'][:120]}…")
                if limit is not None and received >= limit:
                    break

        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            import json

            with out_path.open("w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
            logger.info("Wrote %s frame summaries -> %s", len(records), out_path.resolve())

        if received == 0:
            page_url = self._page.url if self._page else "?"
            logger.warning(
                "No frames received (page=%s, sockets=%s). "
                "Keep CDP Chrome on %s until the live line loads, then retry.",
                page_url,
                len(self._ws_urls),
                self._config.browser_url,
            )
        elif feed is not None:
            summary = state_summary(feed)
            print(
                f"\nParsed {summary.fixtures} soccer fixture(s), "
                f"{summary.odds_markets} with 1X2 odds "
                f"({feed.frame_count} logical messages)\n"
            )
            print_odds_snapshot(feed, live_only=live_only)

        return received

    def collect_frames(self, deadline: float) -> list[str]:
        """Drain raw ZAP frames from browser WebSockets until deadline."""
        self._ensure_ws_listener()
        if self._config.wait_for_cloudflare and self._page is not None:
            url, title, body_text = self._read_page_state()
            if is_cloudflare_challenge(url=url, title=title, body_text=body_text):
                self.ensure_bet365_ready(timeout=120.0)
            elif not is_live_hub_url(url):
                self._navigate_to_live_hub()
        frames: list[str] = []
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                frames.append(self._frame_queue.get(timeout=min(0.25, remaining)))
            except queue.Empty:
                if self._page is not None:
                    self._page.wait_for_timeout(50)
                continue
        return frames

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    def __enter__(self) -> Bet365BrowserSession:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def capture_from_browser(config: Bet365Config | None = None) -> CapturedSession:
    cfg = config or Bet365Config.from_env()
    session = Bet365BrowserSession(cfg)
    try:
        return session.capture()
    finally:
        session.close()


def listen_from_browser(
    config: Bet365Config | None = None,
    *,
    duration: float | None = None,
    max_messages: int | None = None,
    output: Path | None = None,
    parse_odds: bool = False,
    live_only: bool = False,
) -> int:
    """Listen to ZAP frames via CDP Chrome (no separate Python WebSocket)."""
    cfg = config or Bet365Config.from_env()
    session = Bet365BrowserSession(cfg)
    try:
        return session.listen(
            duration=duration,
            max_messages=max_messages,
            output=output,
            parse_odds=parse_odds,
            live_only=live_only,
            verbose=not parse_odds,
        )
    finally:
        session.close()
