"""Apply Liga Stavok WebSocket JSON Patch operations to an event document."""

from __future__ import annotations

import copy
from typing import Any


def apply_patch(document: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply replace-only patches (as sent on /notifications/v3/eventUpdated)."""
    doc = copy.deepcopy(document)
    for op in operations:
        if op.get("op") != "replace":
            continue
        path = op.get("path", "")
        if not path.startswith("/"):
            continue
        segments = [s for s in path.strip("/").split("/") if s]
        if not segments:
            continue
        target: Any = doc
        for segment in segments[:-1]:
            if isinstance(target, dict):
                if segment not in target:
                    target[segment] = {}
                target = target[segment]
            else:
                break
        else:
            if isinstance(target, dict):
                target[segments[-1]] = op.get("value")
    return doc
