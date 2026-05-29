"""Build POST bodies for Liga Stavok eventsList v8 API."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

# All live sports, main markets — mirrors ligastavok.ru Live tab (no gameId filter).
DEFAULT_LIVE_ALL_BODY: dict[str, Any] = {
    "limit": 80,
    "skip": 0,
    "ns": "live",
    "topEvents": False,
    "view": "priority",
    "widgetVideo": False,
    "proposedTypes": ["MAINOFFER"],
}


def parse_body(raw: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return deepcopy(raw)
    text = raw.strip()
    if not text:
        return None
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"Snapshot body must be a JSON object, got {type(parsed)}")
    return parsed


def live_all_body(*, limit: int = 80) -> dict[str, Any]:
    body = deepcopy(DEFAULT_LIVE_ALL_BODY)
    body["limit"] = limit
    return body


def apply_live_all(body: dict[str, Any]) -> dict[str, Any]:
    """Strip sport filter and force live namespace (Fonbet-style all live sports)."""
    patched = deepcopy(body)
    patched.pop("gameId", None)
    patched["ns"] = "live"
    patched.setdefault("topEvents", False)
    patched.setdefault("view", "priority")
    patched.setdefault("widgetVideo", False)
    patched.setdefault("proposedTypes", ["MAINOFFER"])
    return patched


def serialize_body(body: dict[str, Any], *, skip: int | None = None) -> str:
    payload = deepcopy(body)
    if skip is not None:
        payload["skip"] = skip
    return json.dumps(payload, separators=(",", ":"))
