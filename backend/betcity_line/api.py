"""HTTP client for Betcity prematch /d/off/events."""

from __future__ import annotations

import logging
from typing import Any

import requests

from betcity_line.config import BetcityLineConfig

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://betcity.ru/",
    "Origin": "https://betcity.ru",
}


class BetcityLineApiError(Exception):
    pass


def fetch_packet(
    url: str,
    *,
    timeout: float | tuple[float, float] = 90.0,
) -> dict[str, Any]:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise BetcityLineApiError(f"Expected JSON object from {url}")
    return data


def fetch_snapshot(config: BetcityLineConfig | None = None) -> dict[str, Any]:
    cfg = config or BetcityLineConfig.from_env()
    url = cfg.snapshot_url()
    logger.info("Fetching Betcity line snapshot: %s", url)
    return fetch_packet(url, timeout=cfg.request_timeout())


def fetch_delta(md: int, config: BetcityLineConfig | None = None) -> dict[str, Any]:
    cfg = config or BetcityLineConfig.from_env()
    url = cfg.delta_url(md)
    logger.info("Fetching Betcity line delta: md=%s", md)
    return fetch_packet(url, timeout=cfg.request_timeout())


def packet_ntime(packet: dict[str, Any]) -> int | None:
    """Cursor for next md= request — reply.ntime (Fonbet packetVersion analogue)."""
    reply = packet.get("reply")
    if isinstance(reply, dict) and reply.get("ntime") is not None:
        try:
            return int(reply["ntime"])
        except (TypeError, ValueError):
            pass
    if packet.get("ntime") is not None:
        try:
            return int(packet["ntime"])
        except (TypeError, ValueError):
            pass
    return None


def is_snapshot_packet(packet: dict[str, Any], *, had_md: bool) -> bool:
    """Full replace when request had no md cursor."""
    return not had_md
