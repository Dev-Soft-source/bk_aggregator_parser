"""Bet365 ZAP wire protocol helpers (binary-framed messages)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Delimiters
RECORD = "\x01"
FIELD = "\x02"
HANDSHAKE = "\x03"
MESSAGE = "\x08"
ENCODING_NONE = "\x00"

# Message types
TYPE_TOPIC_LOAD = "\x14"
TYPE_DELTA = "\x15"
TYPE_SUBSCRIBE = "\x16"
TYPE_PING_CLIENT = "\x19"
TYPE_TOPIC_STATUS = "\x23"


@dataclass
class ZapFrame:
    """One logical frame from a ZAP WebSocket payload."""

    raw: str
    frame_type: str | None
    topic: str | None
    body: str
    segments: list[str]


def handshake_session_message(session_id: str) -> str:
    """Initial handshake with pstk session id only (older flow)."""
    return f"{TYPE_TOPIC_STATUS}{HANDSHAKE}P{RECORD}__time,S_{session_id}{ENCODING_NONE}"


def handshake_full_message(session_id: str, nst_token: str) -> str:
    """Handshake with session + NST token (newer flow)."""
    return f"#{HANDSHAKE}P{RECORD}__time,S_{session_id},D_{nst_token}{ENCODING_NONE}"


def subscribe_message(topic: str) -> str:
    return f"{TYPE_SUBSCRIBE}{ENCODING_NONE}{topic}{RECORD}"


def subscribe_all(topics: tuple[str, ...]) -> str:
    """Single subscribe frame for multiple topics (comma-separated)."""
    joined = ",".join(topics)
    return f"{TYPE_SUBSCRIBE}{ENCODING_NONE}{joined}{RECORD}"


def split_frames(payload: str) -> list[str]:
    """Split a WebSocket payload on ZAP message delimiter."""
    if not payload:
        return []
    return [part for part in payload.split(MESSAGE) if part]


def parse_frame(chunk: str) -> ZapFrame:
    """Best-effort parse of one ZAP chunk."""
    frame_type = chunk[0] if chunk else None
    topic = None
    body = chunk
    segments: list[str] = []

    if RECORD in chunk:
        segments = chunk.split(RECORD)
        head = segments[0]
        if FIELD in head:
            topic = head.split(FIELD, 1)[0].lstrip(TYPE_TOPIC_LOAD + TYPE_DELTA)
        body = RECORD.join(segments[1:]) if len(segments) > 1 else chunk

    return ZapFrame(
        raw=chunk,
        frame_type=frame_type,
        topic=topic,
        body=body,
        segments=segments,
    )


def frame_summary(frame: ZapFrame) -> dict[str, Any]:
    return {
        "type": frame.frame_type,
        "topic": frame.topic,
        "body_len": len(frame.body),
        "preview": frame.body[:200] if frame.body else "",
    }
