"""Betcity live WebSocket client — raw frame dump (protocol explorer)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

from betcity_live.config import BetcityConfig

logger = logging.getLogger(__name__)


class BetcityWsError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawFrame:
    index: int
    received_at: float
    kind: str  # "text" | "binary"
    data: bytes
    text: str | None

    @property
    def preview(self) -> str:
        if self.text is not None:
            body = self.text.replace("\n", "\\n")
            if len(body) > 240:
                return body[:240] + "…"
            return body
        return f"<{len(self.data)} binary bytes>"


def _format_connect_error(exc: BaseException) -> str:
    message = str(exc)
    lower = message.lower()
    if "403" in message or "forbidden" in lower:
        return (
            f"{exc}\n"
            "Hint: HTTP 403 — set BETCITY_COOKIE from DevTools (Application → Cookies) "
            "or pass --cookie. See betcity_live/README.md."
        )
    if "401" in message or "unauthorized" in lower:
        return (
            f"{exc}\n"
            "Hint: unauthorized — refresh the page on betcity.ru and copy a fresh cookie."
        )
    return message


class BetcityWsClient:
    def __init__(self, config: BetcityConfig | None = None) -> None:
        self._config = config or BetcityConfig.from_env()

    async def _connect(self):
        try:
            import websockets
        except ImportError as exc:
            raise BetcityWsError(
                "Install websockets: pip install websockets"
            ) from exc

        url = self._config.ws_url
        headers = self._config.ws_headers()
        logger.info("Connecting %s", url)
        try:
            return await websockets.connect(
                url,
                additional_headers=headers,
                max_size=None,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=30,
            )
        except Exception as exc:
            raise BetcityWsError(_format_connect_error(exc)) from exc

    async def stream_frames(self) -> AsyncIterator[RawFrame]:
        """Connect and yield raw frames until the socket closes."""
        ws = await self._connect()
        index = 0
        try:
            async for message in ws:
                index += 1
                now = time.time()
                if isinstance(message, bytes):
                    try:
                        text = message.decode("utf-8")
                        kind = "text"
                        data = message
                    except UnicodeDecodeError:
                        text = None
                        kind = "binary"
                        data = message
                else:
                    text = str(message)
                    kind = "text"
                    data = text.encode("utf-8", errors="replace")

                yield RawFrame(
                    index=index,
                    received_at=now,
                    kind=kind,
                    data=data,
                    text=text,
                )
        except Exception as exc:
            raise BetcityWsError(_format_connect_error(exc)) from exc
        finally:
            await ws.close()


async def listen(
    config: BetcityConfig,
    *,
    duration: float | None = None,
    max_frames: int | None = None,
    save_dir: Path | None = None,
    on_frame: Callable[[RawFrame], None] | None = None,
) -> int:
    """Listen for up to `duration` seconds; return number of frames received."""
    duration = config.listen_seconds if duration is None else duration
    max_frames = config.max_frames if max_frames is None else max_frames
    client = BetcityWsClient(config)
    deadline = time.time() + duration
    count = 0

    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)

    try:
        async for frame in client.stream_frames():
            count += 1
            if on_frame:
                on_frame(frame)
            else:
                print(f"[{frame.index}] {frame.kind}: {frame.preview}")

            if save_dir is not None:
                ext = "txt" if frame.kind == "text" else "bin"
                path = save_dir / f"frame_{frame.index:05d}_{int(frame.received_at)}.{ext}"
                path.write_bytes(frame.data)

            if max_frames is not None and count >= max_frames:
                break
            if time.time() >= deadline:
                break
    except asyncio.CancelledError:
        raise
    except BetcityWsError:
        raise
    except Exception as exc:
        raise BetcityWsError(_format_connect_error(exc)) from exc

    return count


def listen_sync(
    config: BetcityConfig,
    *,
    duration: float | None = None,
    max_frames: int | None = None,
    save_dir: Path | None = None,
    on_frame: Callable[[RawFrame], None] | None = None,
) -> int:
    return asyncio.run(
        listen(
            config,
            duration=duration,
            max_frames=max_frames,
            save_dir=save_dir,
            on_frame=on_frame,
        )
    )
