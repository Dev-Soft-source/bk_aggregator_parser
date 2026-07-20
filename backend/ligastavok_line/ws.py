"""Liga Stavok WebSocket client (JSON-RPC subscribe + patch updates)."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Iterator

from ligastavok_line.api import build_ws_handshake
from ligastavok_line.config import LigastavokApiConfig

logger = logging.getLogger(__name__)


class LigastavokWsError(RuntimeError):
    pass


HandshakeProvider = Callable[[bool], tuple[list[str], str | None]]


class LigastavokWsClient:
    def __init__(
        self,
        config: LigastavokApiConfig | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._config = config or LigastavokApiConfig.from_env()
        self._extra_headers = extra_headers
        self._request_id = 0

    def _handshake(self) -> tuple[list[str], str | None]:
        return build_ws_handshake(
            self._config,
            self._extra_headers,
            fresh_request_id=True,
        )

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def subscribe_message(self, event_ids: list[str]) -> dict[str, Any]:
        return {
            "method": "subscribe",
            "params": {
                "method": self._config.ws_subscribe_method,
                "args": {"ids": event_ids},
                "meta": {"applicationName": self._config.application_name},
            },
            "id": self._next_id(),
        }

    def stream_updates(
        self,
        event_ids: list[str],
        *,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        max_messages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Connect, subscribe, yield raw JSON-RPC messages (one-shot session)."""
        session = PersistentWsSession(
            self._config,
            lambda _force: build_ws_handshake(
                self._config,
                self._extra_headers,
                fresh_request_id=True,
            ),
        )
        try:
            if not session.ensure_connected(event_ids, force_cookies=False):
                raise LigastavokWsError("WebSocket connect failed")
            received = 0
            while max_messages is None or received < max_messages:
                msg = session.read_one(timeout=1.0)
                if msg is None:
                    if not session.is_connected():
                        break
                    continue
                if on_message:
                    on_message(msg)
                received += 1
                yield msg
        finally:
            session.close()


class PersistentWsSession:
    """Keep one WebSocket open between HTTP polls (browser-like behaviour)."""

    def __init__(
        self,
        config: LigastavokApiConfig,
        handshake_provider: HandshakeProvider,
    ) -> None:
        self._config = config
        self._handshake_provider = handshake_provider
        self._ws_app: Any = None
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._connected = threading.Event()
        self._closed = threading.Event()
        self._connect_error: list[str] = []
        self._event_ids: list[str] = []
        self._request_id = 0
        self._lock = threading.Lock()
        self._last_403_log = 0.0

    def is_connected(self) -> bool:
        return self._connected.is_set() and not self._closed.is_set()

    def ensure_connected(
        self,
        event_ids: list[str],
        *,
        force_cookies: bool = False,
    ) -> bool:
        with self._lock:
            ids_changed = event_ids != self._event_ids
            self._event_ids = list(event_ids)

            if self.is_connected():
                if ids_changed:
                    self._send_subscribe()
                return True

            self._close_locked()
            return self._connect_locked(force_cookies=force_cookies)

    def read_until(self, deadline: float) -> Iterator[dict[str, Any]]:
        while time.time() < deadline:
            if self._closed.is_set() and self._queue.empty():
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            msg = self.read_one(timeout=min(0.25, remaining))
            if msg is not None:
                yield msg

    def read_one(self, timeout: float) -> dict[str, Any] | None:
        try:
            item = self._queue.get(timeout=max(0.05, timeout))
        except queue.Empty:
            return None
        if item is None:
            return None
        return item

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _subscribe_payload(self) -> dict[str, Any]:
        return {
            "method": "subscribe",
            "params": {
                "method": self._config.ws_subscribe_method,
                "args": {"ids": self._event_ids},
                "meta": {"applicationName": self._config.application_name},
            },
            "id": self._next_id(),
        }

    def _send_subscribe(self) -> None:
        if self._ws_app is None or not self._event_ids:
            return
        try:
            self._ws_app.send(json.dumps(self._subscribe_payload()))
            logger.debug("WebSocket re-subscribed to %s events", len(self._event_ids))
        except Exception as exc:
            logger.warning("WebSocket re-subscribe failed: %s", exc)
            self._close_locked()

    def _connect_locked(self, *, force_cookies: bool) -> bool:
        if not self._event_ids:
            return False

        try:
            import websocket  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LigastavokWsError(
                "websocket-client is required. pip install websocket-client"
            ) from exc

        header_lines, cookie = self._handshake_provider(force_cookies)
        self._connect_error.clear()
        self._connected.clear()
        self._closed.clear()

        def on_open(ws_app: Any) -> None:
            self._connected.set()
            ws_app.send(json.dumps(self._subscribe_payload()))
            logger.info("WebSocket connected, subscribed to %s events", len(self._event_ids))

        def on_data(_ws: Any, message: str) -> None:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("Non-JSON WS message: %s", message[:200])
                return
            self._queue.put(payload)

        def on_error(_ws: Any, error: Exception) -> None:
            self._connect_error.append(str(error))
            if "403" in str(error):
                now = time.time()
                if now - self._last_403_log > 60:
                    self._last_403_log = now
                    logger.warning(
                        "WebSocket 403 — ensure Chrome is on ligastavok.ru "
                        "(CDP) or refresh capture.curl cookies"
                    )
            else:
                logger.error("WebSocket error: %s", error)
            self._connected.clear()
            self._closed.set()

        def on_close(_ws: Any, *_args: Any) -> None:
            self._connected.clear()
            self._closed.set()
            self._queue.put(None)

        self._ws_app = websocket.WebSocketApp(
            self._config.ws_url,
            header=header_lines,
            cookie=cookie,
            on_open=on_open,
            on_message=on_data,
            on_error=on_error,
            on_close=on_close,
        )

        self._thread = threading.Thread(
            target=lambda: self._ws_app.run_forever(
                ping_interval=20,
                ping_timeout=10,
                origin="https://www.ligastavok.ru",
            ),
            daemon=True,
        )
        self._thread.start()

        deadline = time.time() + self._config.ws_timeout
        while time.time() < deadline and not self._closed.is_set():
            if self._connected.is_set():
                return True
            time.sleep(0.05)

        self._close_locked()
        return False

    def _close_locked(self) -> None:
        self._connected.clear()
        self._closed.set()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass
            self._ws_app = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


def parse_update_message(message: dict[str, Any]) -> tuple[int | None, list[dict[str, Any]]]:
    """Extract (event_id, patch_ops) from an eventUpdated push message."""
    result = message.get("result")
    if not isinstance(result, dict):
        return None, []
    payload = result.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "update":
        return None, []
    event_id = payload.get("id")
    data = payload.get("data")
    if not isinstance(data, list):
        return None, []
    eid = int(event_id) if event_id is not None else None
    return eid, data
