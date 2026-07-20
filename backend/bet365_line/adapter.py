"""Bet365 line browser ZAP adapter — taps prematch feed for all sports."""

from __future__ import annotations

import logging
import queue
import time
from collections.abc import Iterator
from typing import Any

from adapters.base import Change, PacketSummary
from bet365.browser_session import Bet365BrowserSession
from bet365.config import Bet365Config
from bet365.protocol import split_frames
from bet365.state import ZapFeedState
from bet365_line.config import line_config_from_env, line_initial_load_seconds_from_env
from bet365_line.hub import (
    SPORT_TAB_LABELS,
    is_line_hub_url,
    is_sport_list_url,
    sport_class_ids_from_env,
    sport_list_url,
)
from bet365_line.mapper import map_state_to_changes, state_summary
from bet365_line.state_export import prematch_events_with_odds

logger = logging.getLogger(__name__)


class Bet365LineAdapter:
    code = "bet365-line"
    display_name = "Bet365 Line"

    def __init__(self, config: Bet365Config | None = None) -> None:
        self._config = config or line_config_from_env()
        self._session: Bet365BrowserSession | None = None
        self._state = ZapFeedState()
        self._started = False
        self._error_count = 0
        self._last_error: str | None = None
        self._last_chunks = 0
        self._empty_poll_streak = 0
        self._poll_iteration = 0
        self._initial_load_seconds = line_initial_load_seconds_from_env()
        self._cookie_last_attempt = 0.0
        self._sport_ids = sport_class_ids_from_env()
        self._sport_index = 0

    def start(self) -> None:
        if self._started:
            return
        self._session = Bet365BrowserSession(self._config)
        self._session.start()
        self._bootstrap_line_page()
        self._started = True
        mode = "safe" if self._config.safe_mode else "standard"
        page_url = self._page_url()
        logger.info(
            "Bet365 line feed ready (CDP %s, sports=%s, page=%s, interval %.1fs, %s mode)",
            self._config.browser_cdp_url,
            ",".join(str(i) for i in self._sport_ids),
            page_url[:120],
            self._config.poll_interval,
            mode,
        )
        print(f"  page URL: {page_url or '(unknown)'}")
        print(f"  sports: {', '.join(f'B{i}' for i in self._sport_ids)}")

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self._started = False

    def _page_url(self) -> str:
        if self._session is None or self._session._page is None:
            return ""
        try:
            return self._session._page.url or ""
        except Exception:
            return ""

    def _on_line_hub(self) -> bool:
        return is_line_hub_url(self._page_url())

    def _drain_frame_queue(self) -> None:
        """Empty the CDP frame queue without replacing it (listeners keep this object)."""
        session = self._session
        if session is None:
            return
        while True:
            try:
                session._frame_queue.get_nowait()
            except queue.Empty:
                break

    def _reset_feed_state(self) -> None:
        """Wipe parsed fixtures only — keep ZAP socket listeners + queue object."""
        self._state = ZapFeedState()
        self._drain_frame_queue()

    def _dismiss_cookies_now(self) -> bool:
        session = self._session
        if session is None or session._page is None:
            return False
        now = time.monotonic()
        if now - self._cookie_last_attempt < 8.0:
            return False
        self._cookie_last_attempt = now
        page = session._page
        ok = session._click_cookie_accept(page)
        if ok:
            session._cookie_banner_seen_since = None
            session._cookie_banner_notice_printed = False
            print("Cookie banner accepted.")
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
        return ok

    def _safe_goto(self, target: str, *, force: bool = False) -> None:
        session = self._session
        if session is None or session._page is None:
            return
        page = session._page
        current = self._page_url()
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)

        # Do not bounce an open sport list back to bare #/AO/.
        if (
            not force
            and is_sport_list_url(current)
            and "#/AO" in target
            and "#/AS" not in target
        ):
            return
        if not force and current.rstrip("/") == target.rstrip("/"):
            return

        try:
            logger.info("Opening %s (was %s)", target, current[:100])
            print(f"Opening {target} …")
            page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1000)
        except Exception as exc:
            logger.warning("goto %s failed: %s", target, exc)
            return
        print(f"Line page: {self._page_url()}")

    def _wait_for_zap(self, timeout: float = 45.0) -> bool:
        """
        Ready when ZAP sockets are known OR frames are arriving.

        After #/HO/ → #/AS/ the SPA often **reuses** the same WebSocket —
        clearing `_ws_urls` and waiting for a new connect is wrong.
        """
        session = self._session
        if session is None:
            return False
        session._ensure_ws_listener()
        if session._ws_urls:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if session._ws_urls or session._uid:
                return True
            # Frames may still arrive on sockets opened before we started waiting.
            try:
                raw = session._frame_queue.get(timeout=0.35)
            except queue.Empty:
                self._dismiss_cookies_now()
                continue
            for part in split_frames(raw):
                self._state.apply_chunk(part)
            return True
        logger.warning(
            "No ZAP yet (sockets=%s) — soft-reload line page",
            len(session._ws_urls),
        )
        return bool(session._ws_urls or session._uid)

    def _soft_reload_to_reattach_zap(self) -> None:
        """F5 once so Playwright can attach to fresh ZAP sockets if needed."""
        session = self._session
        if session is None or session._page is None:
            return
        if session._ws_urls:
            return
        page = session._page
        timeout_ms = int(self._config.browser_timeout_seconds * 1000)
        try:
            print("No ZAP sockets recorded — reloading page to re-attach …")
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
        except Exception as exc:
            logger.warning("reload for ZAP reattach failed: %s", exc)
        session._ensure_ws_listener()
        self._wait_for_zap(20.0)

    def _scroll_line_list(self, page: Any) -> None:
        try:
            for _ in range(5):
                page.evaluate(
                    "() => window.scrollBy(0, Math.max(700, window.innerHeight * 0.9))"
                )
                page.wait_for_timeout(500)
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
        except Exception as exc:
            logger.debug("scroll skipped: %s", exc)

    def _click_sport_tab(self, label: str) -> bool:
        session = self._session
        if session is None or session._page is None:
            return False
        page = session._page
        try:
            tab = page.get_by_text(label, exact=True)
            if tab.count() == 0:
                return False
            target = tab.first
            if not target.is_visible(timeout=600):
                return False
            target.click(timeout=2500)
            logger.info("Selected sport tab %r", label)
            print(f"Selected sport tab: {label}")
            page.wait_for_timeout(1500)
            return True
        except Exception:
            return False

    def _open_sport(self, sport_class_id: int) -> None:
        """Open one sport list (#/AS/B{n}/) and scroll so ZAP loads that book."""
        session = self._session
        if session is None or session._page is None:
            return
        page = session._page
        self._dismiss_cookies_now()
        target = sport_list_url(sport_class_id)
        self._safe_goto(target, force=True)
        try:
            page.wait_for_timeout(1200)
        except Exception:
            pass
        self._dismiss_cookies_now()
        self._scroll_line_list(page)
        # Do NOT clear ws_urls / replace frame_queue — SPA reuses the ZAP socket.
        session._ensure_ws_listener()
        print(f"Sport line view B{sport_class_id}: {self._page_url()}")

    def _cycle_all_sports(self, *, dwell_seconds: float = 4.0) -> int:
        """
        Visit every configured sport class, accumulate ZAP into self._state.

        Bet365 only streams odds for the visible sport — so we rotate tabs/URLs.
        """
        chunks = 0
        for sport_id in self._sport_ids:
            self._open_sport(sport_id)
            # Short check — sockets from #/HO/ usually remain attached.
            self._wait_for_zap(3.0)
            chunks += self._drain_frames_until(time.time() + dwell_seconds)
            fixtures = len(prematch_events_with_odds(self._state))
            sports_n = len(
                {
                    e.sport_class
                    for e in prematch_events_with_odds(self._state)
                    if e.sport_class is not None
                }
            )
            logger.info(
                "After B%s: fixtures=%s sports=%s chunks=%s sockets=%s",
                sport_id,
                fixtures,
                sports_n,
                chunks,
                len(self._session._ws_urls) if self._session else 0,
            )
            print(
                f"  after B{sport_id}: fixtures={fixtures} sports={sports_n} "
                f"(chunks={chunks})"
            )
        return chunks

    def _advance_one_sport(self) -> None:
        """Rotate to the next sport on each recover / periodic prime."""
        if not self._sport_ids:
            return
        sport_id = self._sport_ids[self._sport_index % len(self._sport_ids)]
        self._sport_index += 1
        self._open_sport(sport_id)

    def _bootstrap_line_page(self) -> None:
        """Open AO shell, then walk all sports so ZAP fills the line book."""
        url = self._page_url()
        if not is_line_hub_url(url):
            self._safe_goto(self._config.browser_url)
        self._dismiss_cookies_now()
        # Keep existing ZAP listeners from auth — only clear parsed state.
        self._reset_feed_state()
        if self._session and not self._session._ws_urls:
            self._soft_reload_to_reattach_zap()
        clicked_any = False
        for label in SPORT_TAB_LABELS[:8]:
            if self._click_sport_tab(label):
                clicked_any = True
                break
        if not clicked_any:
            self._open_sport(self._sport_ids[0] if self._sport_ids else 1)
        self._wait_for_zap(8.0)
        if self._session and not self._session._ws_urls:
            self._soft_reload_to_reattach_zap()
        self._warmup_all_sports()

    def _warmup_all_sports(self) -> None:
        seconds = max(30.0, self._initial_load_seconds)
        print(
            f"Loading ALL line sports via ZAP "
            f"({len(self._sport_ids)} sports, up to {seconds:.0f}s) …"
        )
        started = time.time()
        chunks = self._cycle_all_sports(dwell_seconds=min(5.0, seconds / max(len(self._sport_ids), 1)))

        # If time remains and still thin, cycle again.
        while time.time() - started < seconds:
            fixtures = len(prematch_events_with_odds(self._state))
            sports = {
                e.sport_class
                for e in prematch_events_with_odds(self._state)
                if e.sport_class is not None
            }
            if fixtures > 0 and len(sports) >= min(3, len(self._sport_ids)):
                break
            remaining = seconds - (time.time() - started)
            if remaining < 8:
                break
            chunks += self._cycle_all_sports(
                dwell_seconds=min(3.0, remaining / max(len(self._sport_ids), 1))
            )

        summary = state_summary(self._state)
        sports_n = len(
            {
                e.sport_class
                for e in prematch_events_with_odds(self._state)
                if e.sport_class is not None
            }
        )
        print(
            f"Warmup done: {chunks} chunks, {summary.fixtures} prematch fixtures, "
            f"{sports_n} sports, {summary.odds_outcomes} outcomes"
        )
        if summary.fixtures == 0:
            logger.warning(
                "Line warmup ended with 0 fixtures (page=%s)",
                self._page_url()[:120],
            )

    def _ensure_on_line_feed(self) -> None:
        url = self._page_url()
        if is_sport_list_url(url) or is_line_hub_url(url):
            return
        self._safe_goto(self._config.browser_url)
        self._advance_one_sport()

    def _drain_frames_until(self, deadline: float) -> int:
        session = self._session
        if session is None:
            return 0
        session._ensure_ws_listener()
        chunks = 0
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                raw = session._frame_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                page = session._page
                if page is not None:
                    try:
                        page.wait_for_timeout(50)
                    except Exception:
                        pass
                continue
            for part in split_frames(raw):
                self._state.apply_chunk(part)
                chunks += 1
        return chunks

    def poll_once(self) -> tuple[list[Change], PacketSummary, int]:
        if not self._started:
            self.start()

        self._poll_iteration += 1
        self._dismiss_cookies_now()
        self._ensure_on_line_feed()

        # Rotate sport every few polls so all books stay warm.
        if self._poll_iteration % 2 == 1:
            self._advance_one_sport()

        deadline = time.time() + self._config.poll_interval
        chunks = self._drain_frames_until(deadline)

        if chunks > 0:
            self._empty_poll_streak = 0
        else:
            self._empty_poll_streak += 1
            threshold = self._config.stale_polls_before_recover
            if self._empty_poll_streak >= threshold and self._session is not None:
                logger.warning("Empty line polls — rotating next sport")
                self._advance_one_sport()
                self._wait_for_zap(15.0)
                self._empty_poll_streak = 0

        version = int(time.time())
        changes = map_state_to_changes(self._state, version=version)
        summary = state_summary(self._state)
        self._last_chunks = chunks
        return changes, summary, chunks

    def stream_poll_changes(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            cycle_start = time.time()
            try:
                changes, summary, chunks = self.poll_once()
                logger.debug(
                    "Line poll %s: %s chunks, %s changes, %s fixtures",
                    iteration,
                    chunks,
                    len(changes),
                    summary.fixtures,
                )
                yield {}, changes, summary
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.warning(
                    "Bet365 line poll iteration %s failed: %s", iteration, exc
                )
                remaining = cycle_start + self._config.poll_interval - time.time()
                if remaining > 0:
                    time.sleep(remaining)

            if max_iterations is not None and iteration >= max_iterations:
                break

    def __enter__(self) -> Bet365LineAdapter:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
