"""Betcity live adapter — direct WS or CDP Chrome frame tap."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from adapters.base import Change, PacketSummary
from betcity_live.browser_session import BetcityBrowserSession, parse_browser_frame
from betcity_live.catalog import BetcityCatalog
from betcity_live.config import BetcityConfig
from betcity_live.mapper import map_state_to_changes, state_summary
from betcity_live.state import BetcityFeedState
from betcity_live.ws_client import BetcityWsClient, BetcityWsError

logger = logging.getLogger(__name__)


class BetcityAdapter:
    code = "betcity"
    display_name = "Betcity"

    def __init__(
        self,
        config: BetcityConfig | None = None,
        *,
        catalog: BetcityCatalog | None = None,
    ) -> None:
        self._config = config or BetcityConfig.from_env()
        self._state = BetcityFeedState()
        self._client = BetcityWsClient(self._config)
        self._browser: BetcityBrowserSession | None = None
        self._catalog = catalog or BetcityCatalog(
            self._config,
            refresh_seconds=self._config.catalog_refresh_seconds,
        )
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._last_chunks = 0
        self._error_count = 0
        self._last_error: str | None = None

    @property
    def catalog(self) -> BetcityCatalog:
        return self._catalog

    @property
    def use_browser(self) -> bool:
        return bool(self._config.use_browser)

    def start(self) -> None:
        if self._started:
            return
        self._catalog.ensure_fresh(force=True)
        if self.use_browser:
            self._browser = BetcityBrowserSession(self._config)
            self._browser.start()
            logger.info(
                "Betcity browser adapter ready (CDP %s, poll %.1fs, catalog=%s events)",
                self._config.browser_cdp_url,
                self._config.poll_interval,
                self._catalog.size,
            )
        else:
            self._loop = asyncio.new_event_loop()
            self._queue = asyncio.Queue()
            self._reader_task = self._loop.create_task(self._read_forever())
            logger.info(
                "Betcity WS adapter ready (%s, poll %.1fs, catalog=%s events)",
                self._config.ws_url,
                self._config.poll_interval,
                self._catalog.size,
            )
        self._started = True

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._loop is not None and self._reader_task is not None:
            self._reader_task.cancel()
            try:
                self._loop.run_until_complete(self._reader_task)
            except (asyncio.CancelledError, Exception):
                pass
            self._loop.close()
        self._loop = None
        self._reader_task = None
        self._queue = None
        self._started = False

    async def _read_forever(self) -> None:
        assert self._queue is not None
        while True:
            try:
                async for frame in self._client.stream_frames():
                    try:
                        packet = json.loads(frame.data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        logger.debug("Skip non-JSON frame: %s", exc)
                        continue
                    if isinstance(packet, dict):
                        await self._queue.put(packet)
            except asyncio.CancelledError:
                raise
            except BetcityWsError as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.warning("Betcity WS disconnected: %s — reconnecting", exc)
                await asyncio.sleep(2.0)
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.exception("Betcity WS reader failed: %s", exc)
                await asyncio.sleep(2.0)

    def _drain_until_direct(self, deadline: float) -> int:
        if self._loop is None or self._queue is None:
            return 0
        chunks = 0
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                packet = self._loop.run_until_complete(
                    asyncio.wait_for(self._queue.get(), timeout=min(remaining, 0.25))
                )
            except (asyncio.TimeoutError, TimeoutError):
                self._loop.run_until_complete(asyncio.sleep(0))
                continue
            self._state.apply_frame(packet)
            chunks += 1
            self._loop.run_until_complete(asyncio.sleep(0))
        return chunks

    def _drain_until_browser(self, deadline: float) -> int:
        if self._browser is None:
            return 0
        chunks = 0
        for text in self._browser.collect_frames(deadline):
            packet = parse_browser_frame(text)
            if packet is None:
                continue
            self._state.apply_frame(packet)
            chunks += 1
        return chunks

    def _drain_until(self, deadline: float) -> int:
        if self.use_browser:
            return self._drain_until_browser(deadline)
        return self._drain_until_direct(deadline)

    def poll_once(self) -> tuple[list[Change], PacketSummary, int]:
        if not self._started:
            self.start()
        self._catalog.ensure_fresh()
        deadline = time.time() + self._config.poll_interval
        chunks = self._drain_until(deadline)

        # Drop finished events (no longer in on-air catalog) from live state.
        if self._catalog.size > 0:
            catalog_ids = self._catalog.event_ids
            ws_only = {
                event_id
                for event_id, event in self._state.events.items()
                if event.main_markets and event_id not in catalog_ids
            }
            removed = self._state.retain_only(catalog_ids | ws_only)
            if removed:
                logger.info("Pruned %s finished events from live state", removed)

        version = int(self._state.last_md or time.time())
        changes = map_state_to_changes(
            self._state,
            version=version,
            catalog=self._catalog,
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
                logger.warning("Betcity poll iteration %s failed: %s", iteration, exc)
                time.sleep(self._config.poll_interval)

            if max_iterations is not None and iteration >= max_iterations:
                break

    def __enter__(self) -> "BetcityAdapter":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
