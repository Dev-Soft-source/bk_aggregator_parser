"""Parse bet365 ZAP message bodies (pipe-separated records)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CLASS_FROM_EV_ID = re.compile(r"C(\d+)A", re.IGNORECASE)
_CLASS_FROM_IT = re.compile(r"^L(\d+)-")

from bet365.protocol import RECORD, ZapFrame, parse_frame

_OPS = frozenset({"F", "U", "I", "D"})


@dataclass
class ZapRecord:
    kind: str
    fields: dict[str, str]


@dataclass
class ZapMessage:
    op: str
    path: str | None
    records: list[ZapRecord]


def parse_fields(segment: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for piece in segment.split(";"):
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        fields[key] = value
    return fields


def split_records(body: str) -> list[ZapRecord]:
    records: list[ZapRecord] = []
    for segment in body.split("|"):
        segment = segment.strip()
        if not segment or ";" not in segment:
            continue
        kind, rest = segment.split(";", 1)
        if not kind or len(kind) > 3:
            continue
        fields = parse_fields(f"{kind};{rest}")
        records.append(ZapRecord(kind=kind, fields=fields))
    return records


def parse_message_body(body: str) -> ZapMessage | None:
    if not body:
        return None
    op = body[0]
    if op not in _OPS:
        return None

    if op == "U":
        payload = body[2:] if len(body) > 2 and body[1] == "|" else body[1:]
        fields = parse_fields(payload.replace("|", ";"))
        return ZapMessage(op=op, path=None, records=[ZapRecord(kind="U", fields=fields)])

    if op == "D":
        return ZapMessage(op=op, path=None, records=[])

    return ZapMessage(op=op, path=None, records=split_records(body))


def frame_path(frame: ZapFrame) -> str | None:
    if not frame.segments:
        return None
    head = frame.segments[0]
    if frame.frame_type and head.startswith(frame.frame_type):
        path = head[len(frame.frame_type) :]
        return path or None
    return head or None


def parse_wire_chunk(chunk: str) -> tuple[ZapFrame, ZapMessage | None]:
    frame = parse_frame(chunk)
    message = parse_message_body(frame.body)
    if message is not None:
        message = ZapMessage(
            op=message.op,
            path=frame_path(frame),
            records=message.records,
        )
    return frame, message


def fractional_to_decimal(odds: str) -> float | None:
    text = (odds or "").strip()
    if not text:
        return None
    if text.isdigit():
        return float(text)
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            return 1.0 + float(num) / float(den)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_match_teams(name: str) -> tuple[str | None, str | None]:
    text = (name or "").strip()
    for sep in (" v ", " vs ", " @ "):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip() or None, right.strip() or None
    return text or None, None


def sport_class_from_event_fields(fields: dict[str, str]) -> int | None:
    """Resolve bet365 sport class from CL, or from EV ID / IT when CL is omitted."""
    cl = field_int(fields, "CL")
    if cl is not None:
        return cl
    ev_id = fields.get("ID") or ""
    match = _CLASS_FROM_EV_ID.search(ev_id)
    if match:
        return int(match.group(1))
    it = fields.get("IT") or ""
    match = _CLASS_FROM_IT.match(it)
    if match:
        return int(match.group(1))
    return None


def field_int(fields: dict[str, str], key: str) -> int | None:
    raw = fields.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def merge_fields(target: dict[str, Any], patch: dict[str, str]) -> None:
    for key, value in patch.items():
        target[key] = value
