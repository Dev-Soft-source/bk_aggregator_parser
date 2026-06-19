"""Bet365 ZAP WebSocket client (async websockets + permessage-deflate)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from bet365.config import Bet365Config
from bet365.protocol import (
    TYPE_DELTA,
    TYPE_TOPIC_LOAD,
    TYPE_TOPIC_STATUS,
    ZapFrame,
    frame_summary,
    handshake_full_message,
    handshake_session_message,
    parse_frame,
    split_frames,
    subscribe_all,
    subscribe_message,
)
from bet365.session import Bet365SessionError, fetch_session_id

logger = logging.getLogger(__name__)


class Bet365WsError(RuntimeError):
    pass


def _permessage_deflate():
    from websockets.extensions import permessage_deflate

    return [
        permessage_deflate.ClientPerMessageDeflateFactory(
            server_max_window_bits=15,
            client_max_window_bits=15,
            compress_settings={"memLevel": 4},
        )
    ]


class Bet365ZapClient:
    def __init__(self, config: Bet365Config | None = None) -> None:
        self._config = config or Bet365Config.from_env()
        self._subscribed = False

    def _handshake_payload(self, session_id: str) -> str:
        if self._config.nst_token:
            return handshake_full_message(session_id, self._config.nst_token)
        return handshake_session_message(session_id)

    async def _connect(self, url: str):
        try:
            import websockets
        except ImportError as exc:
            raise Bet365WsError(
                "Install websockets: pip install websockets"
            ) from exc

        return await websockets.connect(
            url,
            subprotocols=["zap-protocol-v1"],
            extensions=_permessage_deflate(),
            additional_headers=dict(self._config.ws_headers()),
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            open_timeout=30,
        )

    async def _handle_chunk(
        self,
        ws: Any,
        chunk: str,
        *,
        on_frame: Any = None,
    ) -> list[ZapFrame]:
        frames: list[ZapFrame] = []
        for part in split_frames(chunk):
            frame = parse_frame(part)
            frames.append(frame)

            if frame.frame_type == TYPE_TOPIC_STATUS and not self._subscribed:
                for topic in self._config.topics:
                    await ws.send(subscribe_message(topic))
                self._subscribed = True
                logger.info("Subscribed to %s topics", len(self._config.topics))

            if on_frame:
                on_frame(frame)

        return frames

    async def stream_messages(
        self,
        *,
        use_aux: bool | None = None,
        on_frame: Any = None,
    ) -> AsyncIterator[ZapFrame]:
        """Connect, handshake, yield parsed frames until disconnect."""
        use_aux = self._config.use_aux_socket if use_aux is None else use_aux

        try:
            session_id = fetch_session_id(self._config)
        except Bet365SessionError as exc:
            raise Bet365WsError(str(exc)) from exc

        handshake = self._handshake_payload(session_id)
        logger.info("Session id: %s…", session_id[:12])
        logger.info("Connecting %s", self._config.ws_url)

        try:
            ws = await self._connect(self._config.ws_url)
        except Exception as exc:
            raise Bet365WsError(
                f"WebSocket connect failed: {exc}. "
                "Copy Cookie from bet365.com DevTools into BET365_COOKIE, "
                "or use: python main.py listen bet365 --browser"
            ) from exc

        aux_ws = None
        if use_aux:
            try:
                aux_ws = await self._connect(self._config.ws_aux_url)
                await aux_ws.send(handshake)
                logger.info("Aux socket connected: %s", self._config.ws_aux_url)
            except Exception as exc:
                logger.warning("Aux socket failed (optional): %s", exc)
                aux_ws = None

        try:
            async with ws:
                await ws.send(handshake)
                logger.info("Handshake sent (%s bytes)", len(handshake))

                count = 0
                while True:
                    if (
                        self._config.max_messages is not None
                        and count >= self._config.max_messages
                    ):
                        break

                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")

                    for part in split_frames(raw):
                        frame = parse_frame(part)
                        count += 1

                        if frame.frame_type == TYPE_TOPIC_STATUS and not self._subscribed:
                            await ws.send(subscribe_all(self._config.topics))
                            self._subscribed = True
                            logger.info("Subscribed to topics: %s", self._config.topics)

                        if on_frame:
                            on_frame(frame)
                        yield frame

                    if aux_ws is not None:
                        try:
                            aux_raw = await asyncio.wait_for(aux_ws.recv(), timeout=0.01)
                            if isinstance(aux_raw, bytes):
                                aux_raw = aux_raw.decode("utf-8", errors="replace")
                            await self._handle_chunk(ws, aux_raw, on_frame=on_frame)
                        except asyncio.TimeoutError:
                            pass
        finally:
            if aux_ws is not None:
                await aux_ws.close()


async def listen(
    config: Bet365Config | None = None,
    *,
    duration: float | None = None,
    output: Path | None = None,
) -> int:
    """Print (and optionally save) ZAP frames for a period."""
    cfg = config or Bet365Config.from_env()
    duration = duration if duration is not None else cfg.listen_seconds
    out_path = output or (Path(cfg.output_path) if cfg.output_path else None)

    received = 0
    records: list[dict[str, Any]] = []

    def on_frame(frame: ZapFrame) -> None:
        nonlocal received
        received += 1
        summary = frame_summary(frame)
        kind = frame.frame_type or "?"
        print(f"[{received}] type={kind!r} topic={summary.get('topic')!r} len={summary['body_len']}")
        if frame.frame_type in (TYPE_TOPIC_LOAD, TYPE_DELTA) and summary["preview"]:
            print(f"  preview: {summary['preview'][:120]}…")
        records.append({"ts": time.time(), **summary})

    client = Bet365ZapClient(cfg)
    deadline = time.time() + duration

    try:
        async for _frame in client.stream_messages(on_frame=on_frame):
            if time.time() >= deadline:
                break
            if cfg.max_messages is not None and received >= cfg.max_messages:
                break
    except Bet365WsError:
        raise
    except Exception as exc:
        raise Bet365WsError(str(exc)) from exc

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
        print(f"Wrote {len(records)} frame summaries -> {out_path.resolve()}")

    return received


def listen_browser(
    config: Bet365Config | None = None,
    *,
    duration: float | None = None,
    max_messages: int | None = None,
    output: Path | None = None,
    parse_odds: bool = False,
    live_only: bool = False,
) -> int:
    """Tap ZAP frames from CDP Chrome (recommended — no HTTP 403)."""
    from bet365.browser_session import Bet365BrowserError, listen_from_browser

    cfg = config or Bet365Config.from_env()
    try:
        return listen_from_browser(
            cfg,
            duration=duration,
            max_messages=max_messages,
            output=output,
            parse_odds=parse_odds,
            live_only=live_only,
        )
    except Bet365BrowserError as exc:
        raise Bet365WsError(str(exc)) from exc
