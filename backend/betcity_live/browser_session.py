"""Capture Betcity live WebSocket frames via CDP Chrome (Bet365-style)."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from betcity_live.config import BetcityConfig
from betcity_live.ws_client import RawFrame

logger = logging.getLogger(__name__)

_WS_HOST_MARKERS = ("sc.betcity.ru",)


class BetcityBrowserError(RuntimeError):
    pass


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


def _launch_chrome_script(config: BetcityConfig) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "start_chrome_cdp_betcity.ps1"
    if not script.is_file():
        logger.warning("Missing %s", script)
        return
    if sys.platform != "win32":
        logger.warning("Auto-start Chrome CDP is only implemented for Windows")
        return
    env = dict(os.environ)
    if config.proxy:
        env["BETCITY_PROXY"] = config.proxy
    if config.browser_url:
        env["BETCITY_BROWSER_URL"] = config.browser_url
    try:
        parsed = urlparse(config.browser_cdp_url)
        if parsed.port:
            env["BETCITY_CDP_PORT"] = str(parsed.port)
    except Exception:
        pass
    print(f"Starting CDP Chrome via {script.name} …")
    if config.proxy:
        print(f"  proxy: {config.proxy}")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        logger.warning("Chrome launcher exited with code %s", result.returncode)


def _is_betcity_live_ws(url: str) -> bool:
    lower = (url or "").lower()
    return any(marker in lower for marker in _WS_HOST_MARKERS)


class BetcityBrowserSession:
    """Attach to CDP Chrome and tap sc.betcity.ru WebSocket frames."""

    def __init__(self, config: BetcityConfig) -> None:
        self._config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._ws_urls: set[str] = set()
        self._frame_queue: queue.Queue[str] = queue.Queue(maxsize=5000)
        self._context_listener_registered = False
        self._registered_page_ids: set[int] = set()
        self._bootstrap_done = False

    def start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BetcityBrowserError(
                "Playwright required. Run: pip install playwright && playwright install chromium"
            ) from exc

        cdp_url = self._config.browser_cdp_url
        if not cdp_url:
            raise BetcityBrowserError(
                "Set BETCITY_BROWSER_CDP_URL=http://127.0.0.1:9224"
            )

        self._playwright = sync_playwright().start()
        if not _cdp_is_up(cdp_url):
            logger.info("CDP not up — starting Chrome via start_chrome_cdp_betcity.ps1 …")
            _launch_chrome_script(self._config)
            if not _wait_for_cdp(cdp_url, self._config.browser_timeout_seconds):
                raise BetcityBrowserError(
                    f"Chrome CDP not available at {cdp_url}.\n"
                    "Run: .\\scripts\\start_chrome_cdp_betcity.ps1\n"
                    "Open betcity.ru/ru/live in that Chrome window, then retry."
                )

        try:
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise BetcityBrowserError(
                f"Cannot connect to Chrome at {cdp_url}: {exc}"
            ) from exc

        self._context = (
            self._browser.contexts[0]
            if self._browser.contexts
            else self._browser.new_context()
        )
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        self._ensure_ws_listener()
        logger.info(
            "Attached to Chrome CDP: %s (page: %s)",
            cdp_url,
            self._page.url or "(blank)",
        )
        print(
            f"Chrome attached — continuing live socket tap on {self._config.browser_url}"
        )
        try:
            self.bootstrap_websocket_tap()
        except Exception as exc:
            logger.warning(
                "Bootstrap navigation failed (%s) — will keep waiting for socket",
                exc,
            )
        if self._ws_urls:
            print(f"Live WebSocket connected ({len(self._ws_urls)} socket(s)) — polling…")
        else:
            print(
                "Waiting for sc.betcity.ru socket — leave Chrome open on the live page "
                "(press F5 once if needed)."
            )

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
            logger.info("Listening for Betcity WebSocket connections (sc.betcity.ru)")

    def _on_websocket(self, ws: Any) -> None:
        url = str(ws.url or "")
        if not _is_betcity_live_ws(url):
            return
        self._ws_urls.add(url)
        logger.info("Betcity live socket: %s", url)

        def on_frame(payload: str | bytes) -> None:
            try:
                text = (
                    payload
                    if isinstance(payload, str)
                    else payload.decode("utf-8", errors="replace")
                )
                self._frame_queue.put_nowait(text)
            except queue.Full:
                pass

        def on_close() -> None:
            self._ws_urls.discard(url)
            logger.warning("Betcity live socket closed: %s", url)

        ws.on("framereceived", on_frame)
        ws.on("close", on_close)

    def _page_looks_like_live(self) -> bool:
        if self._page is None:
            return False
        current = (self._page.url or "").lower()
        return "betcity.ru" in current and ("/live" in current or "live" in current)

    def _safe_navigate(self, action: str, fn: Any) -> bool:
        """Run a Playwright navigation; treat ERR_ABORTED / timeouts as soft failures."""
        try:
            fn()
            return True
        except Exception as exc:
            message = str(exc)
            soft = (
                "ERR_ABORTED" in message
                or "ERR_TIMED_OUT" in message
                or "ERR_PROXY" in message
                or "ERR_CONNECTION" in message
                or "Timeout" in message
                or "interrupted" in message.lower()
                or "Navigation" in message
                or "Target page" in message
                or "has been closed" in message
            )
            if soft:
                logger.warning("%s soft-failed (%s) — waiting for existing page/socket", action, message.split("\n", 1)[0])
                return False
            raise

    def _navigate_live(self, *, reload_if_on_page: bool = False) -> None:
        if self._page is None:
            return
        url = self._config.browser_url
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)

        # Chrome launcher often already opened the live page; avoid racing goto.
        if self._page_looks_like_live():
            if not reload_if_on_page:
                logger.info("Already on live page (%s) — waiting for WebSocket", self._page.url)
                return
            logger.info("Reloading %s to attach live WebSocket …", url)

            def _reload() -> None:
                self._page.reload(wait_until="commit", timeout=timeout_ms)

            self._safe_navigate("reload", _reload)
            return

        logger.info("Opening %s …", url)

        def _goto() -> None:
            self._page.goto(url, wait_until="commit", timeout=timeout_ms)

        if not self._safe_navigate("goto", _goto):
            # Page may still be loading from the launcher; give it a moment.
            try:
                self._page.wait_for_timeout(1500)
            except Exception:
                pass

    def bootstrap_websocket_tap(self, *, force: bool = False) -> None:
        if self._bootstrap_done and not force and self._ws_urls:
            return
        if self._page is None:
            try:
                self.start()
            except Exception as exc:
                logger.warning("Browser start failed during bootstrap: %s", exc)
                return
        try:
            self._ensure_ws_listener()
        except Exception as exc:
            logger.warning("WS listener setup failed: %s", exc)
            return
        if not self._ws_urls:
            # Prefer waiting on the already-open live tab; only reload if forced
            # and we still have no socket after a short wait.
            try:
                self._navigate_live(reload_if_on_page=False)
            except Exception as exc:
                logger.warning("Navigate soft-failed: %s", exc)
        deadline = time.monotonic() + min(self._config.browser_timeout_seconds, 30.0)
        reloaded = False
        while time.monotonic() < deadline and not self._ws_urls:
            if (
                not reloaded
                and force
                and self._page_looks_like_live()
                and time.monotonic()
                > deadline - min(self._config.browser_timeout_seconds, 30.0) / 2
            ):
                reloaded = True
                try:
                    self._navigate_live(reload_if_on_page=True)
                except Exception as exc:
                    logger.warning("Reload soft-failed: %s", exc)
            if self._page is not None:
                try:
                    self._page.wait_for_timeout(200)
                except Exception:
                    break
        if not self._ws_urls:
            logger.warning(
                "No sc.betcity.ru socket yet — keep CDP Chrome on %s and press F5 once",
                self._config.browser_url,
            )
        else:
            logger.info("Tapping %s Betcity live socket(s)", len(self._ws_urls))
        self._bootstrap_done = True

    def collect_frames(self, deadline: float) -> list[str]:
        """Drain raw live WS frames from browser until deadline."""
        if self._page is None:
            try:
                self.start()
            except Exception as exc:
                logger.warning("Browser unavailable this tick: %s", exc)
                time.sleep(max(0.0, deadline - time.time()))
                return []
        try:
            self._ensure_ws_listener()
        except Exception as exc:
            logger.warning("WS listener lost: %s", exc)
            return []
        if not self._ws_urls:
            try:
                self.bootstrap_websocket_tap(force=True)
            except Exception as exc:
                logger.warning("Bootstrap retry failed: %s", exc)
        frames: list[str] = []
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                frames.append(self._frame_queue.get(timeout=min(0.25, remaining)))
            except queue.Empty:
                if self._page is not None:
                    try:
                        self._page.wait_for_timeout(50)
                    except Exception:
                        break
                continue
        # If the page lost the socket mid-poll, try one reload next tick.
        if not frames and not self._ws_urls:
            try:
                self.bootstrap_websocket_tap(force=True)
            except Exception as exc:
                logger.warning("Socket reattach failed: %s", exc)
        return frames

    def listen(
        self,
        *,
        duration: float | None = None,
        max_frames: int | None = None,
        on_frame: Callable[[RawFrame], None] | None = None,
        save_dir: Path | None = None,
    ) -> int:
        if self._page is None:
            self.start()
        self.bootstrap_websocket_tap()

        timeout = duration if duration is not None else self._config.listen_seconds
        deadline = time.time() + timeout
        limit = max_frames if max_frames is not None else self._config.max_frames
        received = 0

        if save_dir is not None:
            save_dir.mkdir(parents=True, exist_ok=True)

        while time.time() < deadline:
            if limit is not None and received >= limit:
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                text = self._frame_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if self._page is not None:
                    try:
                        self._page.wait_for_timeout(50)
                    except Exception as exc:
                        if "closed" in str(exc).lower():
                            break
                        raise
                continue

            received += 1
            data = text.encode("utf-8")
            frame = RawFrame(
                index=received,
                received_at=time.time(),
                kind="text",
                data=data,
                text=text,
            )
            if on_frame is not None:
                on_frame(frame)
            if save_dir is not None:
                path = save_dir / f"frame_{received:05d}_{int(frame.received_at)}.txt"
                path.write_text(text, encoding="utf-8")

        if received == 0:
            logger.warning(
                "No frames received (page=%s, sockets=%s). Keep CDP Chrome on %s.",
                self._page.url if self._page else "?",
                len(self._ws_urls),
                self._config.browser_url,
            )
        return received

    def close(self) -> None:
        # Detach only — do not kill the user's CDP Chrome window.
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

    def __enter__(self) -> "BetcityBrowserSession":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def listen_from_browser(
    config: BetcityConfig | None = None,
    *,
    duration: float | None = None,
    max_frames: int | None = None,
    on_frame: Callable[[RawFrame], None] | None = None,
    save_dir: Path | None = None,
) -> int:
    cfg = config or BetcityConfig.from_env()
    session = BetcityBrowserSession(cfg)
    try:
        return session.listen(
            duration=duration,
            max_frames=max_frames,
            on_frame=on_frame,
            save_dir=save_dir,
        )
    finally:
        session.close()


def parse_browser_frame(text: str) -> dict[str, Any] | None:
    try:
        packet = json.loads(text)
    except json.JSONDecodeError:
        return None
    return packet if isinstance(packet, dict) else None
