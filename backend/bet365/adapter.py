"""Bet365 browser ZAP adapter — accumulates frames between poll ticks."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from adapters.base import Change, PacketSummary
from bet365.browser_session import Bet365BrowserSession
from bet365.config import Bet365Config
from bet365.mapper import map_state_to_changes, state_summary
from bet365.protocol import split_frames
from bet365.state import ZapFeedState

logger = logging.getLogger(__name__)


class Bet365Adapter:
    code = "bet365"
    display_name = "Bet365"

    def __init__(self, config: Bet365Config | None = None) -> None:
        self._config = config or Bet365Config.from_env()
        self._session: Bet365BrowserSession | None = None
        self._state = ZapFeedState()
        self._started = False
        self._error_count = 0
        self._last_error: str | None = None
        self._last_chunks = 0
        self._empty_poll_streak = 0

    def start(self) -> None:
        if self._started:
            return
        self._session = Bet365BrowserSession(self._config)
        self._session.start()
        self._session.bootstrap_websocket_tap()
        self._started = True
        mode = "safe" if self._config.safe_mode else "standard"
        logger.info(
            "Bet365 browser feed ready (CDP %s, interval %.1fs, %s mode, auto_reload=%s)",
            self._config.browser_cdp_url,
            self._config.poll_interval,
            mode,
            self._config.browser_auto_reload,
        )

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self._started = False

    def _drain_frames_until(self, deadline: float) -> int:
        if self._session is None:
            return 0
        chunks = 0
        for raw in self._session.collect_frames(deadline):
            for part in split_frames(raw):
                self._state.apply_chunk(part)
                chunks += 1
        return chunks

    def poll_once(self) -> tuple[list[Change], PacketSummary, int]:
        """Collect ZAP frames since last tick and map to changes."""
        if not self._started:
            self.start()

        deadline = time.time() + self._config.poll_interval
        chunks = self._drain_frames_until(deadline)

        if chunks > 0:
            self._empty_poll_streak = 0
        else:
            self._empty_poll_streak += 1
            threshold = self._config.stale_polls_before_recover
            if self._empty_poll_streak >= threshold and self._session is not None:
                if self._session.recover_feed_once():
                    self._empty_poll_streak = 0
                elif not self._config.recover_reload:
                    logger.warning(
                        "Still no ZAP frames after %s empty poll(s) — press F5 in CDP Chrome",
                        threshold,
                    )

        dropped = self._state.drop_finished_events()
        if dropped:
            logger.info("Dropped %s finished Bet365 events from live state", dropped)

        version = int(time.time())
        changes = map_state_to_changes(
            self._state,
            version=version,
            live_only=self._config.poll_live_only,
        )
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
                    "Poll %s: %s chunks, %s changes, %s fixtures",
                    iteration,
                    chunks,
                    len(changes),
                    summary.fixtures,
                )
                yield {}, changes, summary
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.warning("Bet365 poll iteration %s failed: %s", iteration, exc)
                remaining = cycle_start + self._config.poll_interval - time.time()
                if remaining > 0:
                    time.sleep(remaining)

            if max_iterations is not None and iteration >= max_iterations:
                break

    def __enter__(self) -> Bet365Adapter:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
