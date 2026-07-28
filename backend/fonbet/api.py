"""HTTP client for Fonbet line API."""

from __future__ import annotations

import logging
import time
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


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _normalize_timeout(timeout: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(timeout, tuple):
        return (float(timeout[0]), float(timeout[1]))
    value = float(timeout)
    return (min(8.0, value), value)


def fetch_packet(
    url: str,
    timeout: float | tuple[float, float] = 30.0,
    *,
    attempts: int = 3,
    retry_sleep: float = 2.0,
) -> dict[str, Any]:
    """
    GET JSON with retries.

    Uses a fresh Session per attempt so a hung TLS handshake cannot poison
    a shared connection pool (common on Windows with SSLEOFError).
    """
    last_exc: BaseException | None = None
    max_attempts = max(1, attempts)
    req_timeout = _normalize_timeout(timeout)

    for attempt in range(1, max_attempts + 1):
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        try:
            if attempt > 1:
                logger.info(
                    "Fonbet request retry %s/%s: %s",
                    attempt,
                    max_attempts,
                    url.split("?", 1)[0],
                )
            response = session.get(url, timeout=req_timeout)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise FonbetApiError(f"Expected JSON object from {url}")
            return data
        except FonbetApiError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt >= max_attempts:
                raise
            logger.warning(
                "Fonbet request failed (attempt %s/%s): %s",
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(retry_sleep * (attempt**2))
        finally:
            try:
                session.close()
            except Exception:
                pass

    if last_exc is not None:
        raise last_exc
    raise FonbetApiError(f"Request failed: {url}")


def fetch_list_light(config: FonbetApiConfig | None = None) -> dict[str, Any]:
    cfg = config or FonbetApiConfig.from_env()
    logger.info(
        "Fetching listLight (timeout connect=%.0fs read=%.0fs retries=%s): %s",
        cfg.connect_timeout,
        cfg.timeout,
        cfg.http_retries,
        cfg.list_light_url,
    )
    return fetch_packet(
        cfg.list_light_url,
        timeout=cfg.request_timeout,
        attempts=cfg.http_retries,
        retry_sleep=cfg.http_retry_sleep,
    )


def fetch_list(version: int, config: FonbetApiConfig | None = None) -> dict[str, Any]:
    cfg = config or FonbetApiConfig.from_env()
    url = cfg.list_url(version)
    logger.info("Fetching list: version=%s", version)
    return fetch_packet(
        url,
        timeout=cfg.request_timeout,
        attempts=cfg.http_retries,
        retry_sleep=cfg.http_retry_sleep,
    )


def packet_version(packet: dict[str, Any]) -> int | None:
    value = packet.get("packetVersion")
    if value is None:
        return None
    return int(value)


def is_snapshot_packet(packet: dict[str, Any]) -> bool:
    """Full line snapshot when fromVersion is absent or zero."""
    from_version = packet.get("fromVersion")
    return from_version is None or int(from_version) == 0
