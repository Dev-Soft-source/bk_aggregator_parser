"""HTTP client for Fonbet line API."""

from __future__ import annotations

import logging
from typing import Any

import requests

from fonbet.config import FonbetApiConfig

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class FonbetApiError(Exception):
    pass


def fetch_packet(url: str, timeout: float = 30.0) -> dict[str, Any]:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise FonbetApiError(f"Expected JSON object from {url}")
    return data


def fetch_list_light(config: FonbetApiConfig | None = None) -> dict[str, Any]:
    cfg = config or FonbetApiConfig.from_env()
    logger.info("Fetching listLight: %s", cfg.list_light_url)
    return fetch_packet(cfg.list_light_url, timeout=cfg.timeout)


def fetch_list(version: int, config: FonbetApiConfig | None = None) -> dict[str, Any]:
    cfg = config or FonbetApiConfig.from_env()
    url = cfg.list_url(version)
    logger.info("Fetching list: version=%s", version)
    return fetch_packet(url, timeout=cfg.timeout)


def packet_version(packet: dict[str, Any]) -> int | None:
    value = packet.get("packetVersion")
    if value is None:
        return None
    return int(value)


def is_snapshot_packet(packet: dict[str, Any]) -> bool:
    """Full line snapshot when fromVersion is absent or zero."""
    from_version = packet.get("fromVersion")
    return from_version is None or int(from_version) == 0
