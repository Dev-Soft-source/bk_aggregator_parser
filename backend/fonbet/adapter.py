"""Fonbet bookmaker adapter (TZ §6.3, Table 6.1)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from adapters.base import Change, EventRef, HealthStatus, PacketSummary, SportRef, TournamentRef
from fonbet import api, mapper
from fonbet.api import _is_retryable
from fonbet.config import FonbetApiConfig

logger = logging.getLogger(__name__)


class FonbetAdapter:
    code = "fonbet"
    display_name = "Fonbet"

    def __init__(
        self,
        api_config: FonbetApiConfig | None = None,
        *,
        known_match_ids: set[int] | None = None,
    ) -> None:
        self._api = api_config or FonbetApiConfig.from_env()
        self._known_match_ids = known_match_ids
        self._version: int | None = None
        self._last_success_at: datetime | None = None
        self._last_packet_version: int | None = None
        self._last_error: str | None = None
        self._poll_count = 0
        self._error_count = 0

    @property
    def known_match_ids(self) -> set[int] | None:
        return self._known_match_ids

    @known_match_ids.setter
    def known_match_ids(self, value: set[int] | None) -> None:
        self._known_match_ids = value

    def load_packet_file(self, path: Path) -> dict[str, Any]:
        import json

        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def discover_sports(self, packet: dict[str, Any]) -> list[SportRef]:
        return mapper.discover_sports(packet)

    def discover_tournaments(self, packet: dict[str, Any]) -> list[TournamentRef]:
        return mapper.discover_tournaments(packet)

    def discover_events(
        self, packet: dict[str, Any], mode: str = "live"
    ) -> list[EventRef]:
        return mapper.discover_events(packet, mode=mode)

    def map_packet_to_changes(
        self,
        packet: dict[str, Any],
        *,
        known_match_ids: set[int] | None = None,
    ) -> list[Change]:
        known = known_match_ids if known_match_ids is not None else self._known_match_ids
        return mapper.map_packet_to_changes(packet, known_match_ids=known)

    def packet_summary(
        self,
        packet: dict[str, Any],
        *,
        known_match_ids: set[int] | None = None,
    ) -> PacketSummary:
        known = known_match_ids if known_match_ids is not None else self._known_match_ids
        return mapper.packet_summary(packet, known_match_ids=known)

    def fetch_next_packet(self) -> dict[str, Any]:
        every = getattr(self._api, "snapshot_every", 0) or 0
        force_snapshot = self._version is None or (
            every > 0 and self._poll_count > 0 and self._poll_count % every == 0
        )
        if force_snapshot:
            return api.fetch_list_light(self._api)
        return api.fetch_list(self._version, self._api)

    def process_packet(self, packet: dict[str, Any]) -> tuple[list[Change], PacketSummary]:
        version = api.packet_version(packet)
        if version is None:
            raise api.FonbetApiError("Response missing packetVersion")

        changes = self.map_packet_to_changes(packet)
        summary = self.packet_summary(packet)
        self._version = version
        self._last_packet_version = version
        self._last_success_at = datetime.now(UTC)
        self._last_error = None
        self._poll_count += 1
        return changes, summary

    def stream_live_changes(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            cycle_started_at = time.monotonic()
            iteration += 1
            try:
                packet = self.fetch_next_packet()
                changes, summary = self.process_packet(packet)
                yield packet, changes, summary
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.exception("Fonbet poll failed: %s", exc)
                self._version = None
                raise

            if max_iterations is not None and iteration >= max_iterations:
                break
            elapsed = time.monotonic() - cycle_started_at
            time.sleep(max(0.0, self._api.poll_interval - elapsed))

    def stream_live_changes_resilient(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]:
        """Poll loop that resets to listLight after errors (same as poll.py)."""
        iteration = 0
        consecutive_failures = 0
        while max_iterations is None or iteration < max_iterations:
            cycle_started_at = time.monotonic()
            iteration += 1
            try:
                packet = self.fetch_next_packet()
                changes, summary = self.process_packet(packet)
                consecutive_failures = 0
                yield packet, changes, summary
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                consecutive_failures += 1
                if _is_retryable(exc):
                    logger.warning(
                        "Fonbet poll iteration %s failed (transient): %s",
                        iteration,
                        exc,
                    )
                else:
                    logger.exception(
                        "Fonbet poll iteration %s failed: %s", iteration, exc
                    )
                self._version = None

            if max_iterations is not None and iteration >= max_iterations:
                break
            if consecutive_failures:
                backoff = min(
                    self._api.failure_backoff_max,
                    self._api.poll_interval * (2 ** min(consecutive_failures - 1, 5)),
                )
                time.sleep(backoff)
            else:
                elapsed = time.monotonic() - cycle_started_at
                time.sleep(max(0.0, self._api.poll_interval - elapsed))

    def health(self) -> HealthStatus:
        ok = self._last_error is None and self._last_success_at is not None
        message = "healthy" if ok else "degraded"
        if self._last_error:
            message = f"last error: {self._last_error}"
        elif self._poll_count == 0:
            message = "not started"
            ok = False

        return HealthStatus(
            ok=ok,
            code=self.code,
            message=message,
            last_success_at=self._last_success_at,
            last_packet_version=self._last_packet_version,
            last_error=self._last_error,
            poll_count=self._poll_count,
            error_count=self._error_count,
        )
