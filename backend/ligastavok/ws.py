"""Liga Stavok WebSocket client (JSON-RPC subscribe + patch updates)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterator

from ligastavok.config import LigastavokApiConfig
from ligastavok.api import merge_request_headers

logger = logging.getLogger(__name__)


class LigastavokWsError(RuntimeError):
    pass


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

    def _ws_header_list(self) -> list[str]:
        merged = merge_request_headers(
            self._config,
            self._extra_headers,
            fresh_request_id=True,
        )
        # websocket-client expects "Key: value" strings
        return [f"{key}: {value}" for key, value in merged.items()]

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
        """Connect, subscribe, yield raw JSON-RPC messages."""
        try:
            import websocket  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LigastavokWsError(
                "websocket-client is required for --live. pip install websocket-client"
            ) from exc

        subscribe = self.subscribe_message(event_ids)
        received = 0
        queue: list[dict[str, Any]] = []
        lock = threading.Lock()
        closed = threading.Event()
        connected = threading.Event()
        connect_error: list[str] = []

        def on_open(ws_app: Any) -> None:
            connected.set()
            ws_app.send(json.dumps(subscribe))
            logger.info("WebSocket connected, subscribed to %s events", len(event_ids))

        def on_data(_ws: Any, message: str) -> None:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("Non-JSON WS message: %s", message[:200])
                return
            with lock:
                queue.append(payload)
            if on_message:
                on_message(payload)

        def on_error(_ws: Any, error: Exception) -> None:
            connect_error.append(str(error))
            logger.error("WebSocket error: %s", error)
            closed.set()

        def on_close(_ws: Any, *_args: Any) -> None:
            closed.set()

        ws = websocket.WebSocketApp(
            self._config.ws_url,
            header=self._ws_header_list(),
            on_open=on_open,
            on_message=on_data,
            on_error=on_error,
            on_close=on_close,
        )

        thread = threading.Thread(
            target=lambda: ws.run_forever(
                ping_interval=20,
                ping_timeout=10,
                origin="https://www.ligastavok.ru",
            ),
            daemon=True,
        )
        thread.start()

        deadline = time.time() + self._config.ws_timeout
        while time.time() < deadline and not closed.is_set():
            if connected.is_set():
                break
            time.sleep(0.05)

        if not connected.is_set():
            closed.set()
            ws.close()
            thread.join(timeout=5)
            hint = (
                " Refresh capture.curl with -b cookies or set LIGASTAVOK_COOKIE in .env."
            )
            if connect_error:
                raise LigastavokWsError(
                    f"WebSocket connect failed: {connect_error[-1]}.{hint}"
                )
            raise LigastavokWsError(
                f"WebSocket connect timeout ({self._config.ws_timeout}s): "
                f"{self._config.ws_url}.{hint}"
            )

        while not closed.is_set():
            with lock:
                if queue:
                    msg = queue.pop(0)
                else:
                    msg = None
            if msg is not None:
                received += 1
                yield msg
                if max_messages is not None and received >= max_messages:
                    break
            else:
                time.sleep(0.05)

        ws.close()
        thread.join(timeout=5)


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
