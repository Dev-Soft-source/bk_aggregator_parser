"""Liga Stavok bookmaker adapter (TZ §6.3)."""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from adapters.base import Change, EventRef, HealthStatus, PacketSummary, SportRef, TournamentRef
from ligastavok_line import mapper
from ligastavok_line.api import CurlRequest, LigastavokApiError, build_ws_handshake, fetch_snapshot, parse_curl_file
from ligastavok_line.config import LigastavokApiConfig
from ligastavok_line.patch import apply_patch
from ligastavok_line.ws import LigastavokWsError, PersistentWsSession, parse_update_message

logger = logging.getLogger(__name__)


class LigastavokAdapter:
    code = "ligastavok"
    display_name = "Liga Stavok"

    def __init__(
        self,
        api_config: LigastavokApiConfig | None = None,
        *,
        known_match_ids: set[int] | None = None,
        cookie_session: Any | None = None,
    ) -> None:
        self._api = api_config or LigastavokApiConfig.from_env()
        self._known_match_ids = known_match_ids
        self._cookie_session = cookie_session
        self._curl_request: CurlRequest | None = None
        self._events_by_id: dict[int, dict[str, Any]] = {}
        self._packet_version = 0
        self._last_success_at: datetime | None = None
        self._last_packet_version: int | None = None
        self._last_error: str | None = None
        self._poll_count = 0
        self._error_count = 0
        self._cookie_refresh_after = self._roll_refresh_interval()
        self._cookie_polls_since_refresh = self._cookie_refresh_after
        self._ws_session: PersistentWsSession | None = None

    def load_packet_file(self, path: Path) -> dict[str, Any]:
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

    def load_curl_file(self, path: Path) -> CurlRequest:
        self._curl_request = parse_curl_file(path)
        return self._curl_request

    def _resolve_curl_request(self) -> CurlRequest:
        if self._curl_request is not None:
            return self._curl_request
        if self._api.curl_file:
            return self.load_curl_file(Path(self._api.curl_file))
        raise LigastavokApiError(
            "HTTP poll requires --curl capture.curl or LIGASTAVOK_CURL_FILE in .env"
        )

    def _roll_refresh_interval(self) -> int:
        lo, hi = self._api.browser_refresh_min, self._api.browser_refresh_max
        if lo is not None and hi is not None:
            return random.randint(lo, hi)
        return self._api.browser_refresh_every

    def _apply_browser_cookies(self, *, force: bool = False) -> None:
        if self._cookie_session is None:
            return
        self._cookie_polls_since_refresh += 1
        if not force and self._cookie_polls_since_refresh < self._cookie_refresh_after:
            return
        header = self._cookie_session.refresh_cookie_header(force_reload=force)
        curl_req = self._resolve_curl_request()
        curl_req.headers["Cookie"] = header
        self._cookie_polls_since_refresh = 0
        self._cookie_refresh_after = self._roll_refresh_interval()
        logger.info("Next cookie refresh in %s poll(s)", self._cookie_refresh_after)

    def cookie_refresh_schedule(self) -> str:
        lo, hi = self._api.browser_refresh_min, self._api.browser_refresh_max
        if lo is not None and hi is not None:
            return f"random {lo}-{hi} polls (next in {self._cookie_refresh_after})"
        return f"every {self._api.browser_refresh_every} polls"

    def fetch_next_packet(self) -> dict[str, Any]:
        curl_req = self._resolve_curl_request()
        self._apply_browser_cookies()
        raw_body = curl_req.body or self._api.snapshot_body
        try:
            return fetch_snapshot(
                self._api,
                url=curl_req.url,
                headers=curl_req.headers,
                method=curl_req.method,
                body=raw_body,
                ns=self._api.snapshot_ns,
                live_all=self._api.live_all_sports,
                max_pages=self._api.snapshot_max_pages,
            )
        except LigastavokApiError as exc:
            if self._cookie_session is not None and "403" in str(exc):
                logger.info("403 after poll — refreshing browser cookies and retrying once")
                self._apply_browser_cookies(force=True)
                return fetch_snapshot(
                    self._api,
                    url=curl_req.url,
                    headers=curl_req.headers,
                    method=curl_req.method,
                    body=raw_body,
                    ns=self._api.snapshot_ns,
                    live_all=self._api.live_all_sports,
                    max_pages=self._api.snapshot_max_pages,
                )
            raise

    def stream_poll_changes(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]:
        """Poll HTTP snapshot every poll_interval seconds (Fonbet-style loop)."""
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            cycle_start = time.time()
            try:
                packet = self.fetch_next_packet()
                changes, summary = self.process_packet(packet)
                yield packet, changes, summary

                ws_changes = self.collect_ws_changes_until(
                    cycle_start + self._api.poll_interval
                )
                if ws_changes:
                    ws_summary = mapper.packet_summary(
                        {
                            "result": {
                                "data": list(self._events_by_id.values()),
                                "ts": self._packet_version,
                            }
                        }
                    )
                    yield packet, ws_changes, ws_summary
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.warning("Liga Stavok poll iteration %s failed: %s", iteration, exc)
                remaining = cycle_start + self._api.poll_interval - time.time()
                if remaining > 0:
                    time.sleep(remaining)

            if max_iterations is not None and iteration >= max_iterations:
                break

    def collect_ws_changes_until(self, deadline: float) -> list[Change]:
        """Listen for WebSocket patches until deadline (fills gap between HTTP snapshots)."""
        remaining = deadline - time.time()
        if remaining <= 0:
            return []

        if not self._api.ws_enabled or not self._events_by_id:
            time.sleep(remaining)
            return []

        # Qrator blocks Python WebSocket handshakes — use the browser's live connection.
        if self._cookie_session is not None and self._cookie_session.has_browser_ws:
            all_changes: list[Change] = []
            for message in self._cookie_session.collect_ws_messages(deadline):
                event_id, ops = parse_update_message(message)
                if event_id is None or not ops:
                    continue
                all_changes.extend(self.apply_ws_update(event_id, ops))
            sleep_for = deadline - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            return all_changes

        event_ids = [str(eid) for eid in self._events_by_id]
        if self._ws_session is None:
            self._ws_session = PersistentWsSession(self._api, self._ws_handshake)

        connected = self._ws_session.ensure_connected(event_ids, force_cookies=False)
        if not connected:
            connected = self._ws_session.ensure_connected(event_ids, force_cookies=True)

        if not connected:
            sleep_for = deadline - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            return []

        all_changes: list[Change] = []
        try:
            for message in self._ws_session.read_until(deadline):
                event_id, ops = parse_update_message(message)
                if event_id is None or not ops:
                    continue
                all_changes.extend(self.apply_ws_update(event_id, ops))
        except Exception as exc:
            logger.warning("WebSocket drain error: %s", exc)
            self._ws_session.close()
            self._ws_session = None

        sleep_for = deadline - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)
        return all_changes

    def _ws_handshake(self, force_cookies: bool) -> tuple[list[str], str | None]:
        curl_req = self._resolve_curl_request()
        if self._cookie_session is not None:
            curl_req.headers["Cookie"] = self._cookie_session.refresh_cookie_header(
                force_reload=force_cookies
            )
        return build_ws_handshake(self._api, curl_req.headers, fresh_request_id=True)

    def bootstrap_from_packet(self, packet: dict[str, Any]) -> None:
        self._events_by_id = {
            int(item["id"]): item for item in mapper.extract_events(packet) if item.get("id")
        }
        self._packet_version = mapper.packet_version(packet)

    def process_packet(self, packet: dict[str, Any]) -> tuple[list[Change], PacketSummary]:
        self.bootstrap_from_packet(packet)
        changes = self.map_packet_to_changes(packet)
        summary = self.packet_summary(packet)
        self._last_packet_version = summary.packet_version
        self._last_success_at = datetime.now(UTC)
        self._last_error = None
        self._poll_count += 1
        return changes, summary

    def apply_ws_update(self, event_id: int, operations: list[dict[str, Any]]) -> list[Change]:
        current = self._events_by_id.get(event_id)
        if not current:
            logger.debug("Patch for unknown event %s", event_id)
            return []
        updated = apply_patch(current, operations)
        self._events_by_id[event_id] = updated
        self._packet_version += 1
        return mapper.map_event_to_changes(
            updated,
            packet_version=self._packet_version,
            from_version=self._packet_version - 1,
        )

    def _ws_headers(self) -> dict[str, str] | None:
        curl_req = self._curl_request
        if curl_req is None and self._api.curl_file:
            try:
                curl_req = self.load_curl_file(Path(self._api.curl_file))
            except Exception:
                return None
        if curl_req is None:
            return None
        if self._cookie_session is not None:
            curl_req.headers["Cookie"] = self._cookie_session.refresh_cookie_header(
                force_reload=False
            )
        return curl_req.headers

    def stream_live_changes(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]:
        if not self._events_by_id:
            raise RuntimeError("Call bootstrap_from_packet() before stream_live_changes()")

        from ligastavok_line.ws import LigastavokWsClient

        client = LigastavokWsClient(self._api, extra_headers=self._ws_headers())
        event_ids = [str(eid) for eid in self._events_by_id]
        iteration = 0

        try:
            updates = client.stream_updates(event_ids, max_messages=max_iterations)
        except LigastavokWsError:
            raise
        except Exception as exc:
            raise LigastavokWsError(str(exc)) from exc

        for message in updates:
            iteration += 1
            event_id, ops = parse_update_message(message)
            if event_id is None or not ops:
                continue
            changes = self.apply_ws_update(event_id, ops)
            summary = mapper.packet_summary(
                {"result": {"data": list(self._events_by_id.values()), "ts": self._packet_version}}
            )
            self._last_success_at = datetime.now(UTC)
            self._last_error = None
            self._poll_count += 1
            yield message, changes, summary

    def close(self) -> None:
        if self._ws_session is not None:
            self._ws_session.close()
            self._ws_session = None
        if self._cookie_session is not None:
            self._cookie_session.close()

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
