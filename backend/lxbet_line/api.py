"""HTTP client for 1xBet LineFeed catalog + Get1x2_VZip events."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from lxbet_line.config import LxbetLineConfig

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://1xlite-55157.pro/",
    "Origin": "https://1xlite-55157.pro",
}

_FETCH_ATTEMPTS = 3
_FETCH_RETRY_SLEEP = 2.0

# Global cap on in-flight HTTP calls (nested sport/champ pools share this).
_http_slots = threading.BoundedSemaphore(1)
_http_slots_lock = threading.Lock()
_http_slots_limit = 1
_request_pause_seconds = 0.5
_session: requests.Session | None = None
_session_lock = threading.Lock()


@dataclass(frozen=True)
class SnapshotResult:
    """Packet plus catalog coverage (for safe prune decisions)."""

    packet: dict[str, Any]
    expected_events: int
    fetched_events: int

    @property
    def coverage(self) -> float:
        if self.expected_events <= 0:
            return 1.0
        return self.fetched_events / float(self.expected_events)


class LxbetLineApiError(Exception):
    pass


def _configure_client(cfg: LxbetLineConfig) -> None:
    """Apply concurrency + pause + shared Session from config."""
    global _http_slots, _http_slots_limit, _request_pause_seconds, _session
    limit = max(1, int(cfg.max_workers))
    pause = max(0.0, float(cfg.request_pause_seconds))
    with _http_slots_lock:
        _request_pause_seconds = pause
        if limit != _http_slots_limit:
            _http_slots = threading.BoundedSemaphore(limit)
            _http_slots_limit = limit
    with _session_lock:
        if _session is not None:
            try:
                _session.close()
            except Exception:
                pass
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=limit,
            max_retries=0,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session


def _get_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            session = requests.Session()
            session.headers.update(DEFAULT_HEADERS)
            adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _session = session
        return _session


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


def fetch_packet(
    url: str,
    *,
    timeout: float = 30.0,
    attempts: int = _FETCH_ATTEMPTS,
) -> dict[str, Any]:
    last_exc: BaseException | None = None
    session = _get_session()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with _http_slots:
                response = session.get(url, timeout=timeout)
                if _request_pause_seconds > 0:
                    time.sleep(_request_pause_seconds)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise LxbetLineApiError(f"Expected JSON object from {url}")
            if data.get("Success") is False:
                raise LxbetLineApiError(
                    f"API Success=false: {data.get('Error') or data.get('ErrorCode')}"
                )
            value = data.get("Value")
            if not isinstance(value, list):
                raise LxbetLineApiError("Response missing Value list")
            return data
        except LxbetLineApiError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt >= attempts:
                raise
            logger.warning(
                "1xBet line request failed (attempt %s/%s): %s",
                attempt,
                attempts,
                exc,
            )
            # Back off harder on TLS/connection drops so the pool can settle.
            time.sleep(_FETCH_RETRY_SLEEP * (attempt**2))
    assert last_exc is not None
    raise last_exc


def merge_packets(*packets: dict[str, Any]) -> dict[str, Any]:
    """Union Value[] by event id I (later packets win on conflict)."""
    by_id: dict[int, dict[str, Any]] = {}
    for packet in packets:
        value = packet.get("Value")
        if not isinstance(value, list):
            continue
        for event in value:
            if not isinstance(event, dict):
                continue
            raw_id = event.get("I")
            try:
                event_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            by_id[event_id] = event
    return {
        "Id": 0,
        "Success": True,
        "Error": "",
        "ErrorCode": 0,
        "Value": list(by_id.values()),
    }


def _sport_catalog(cfg: LxbetLineConfig) -> list[tuple[int, int, str]]:
    """Return [(sport_id, event_count, name), ...] deduped by sport id."""
    packet = fetch_packet(cfg.sports_list_url(), timeout=cfg.timeout)
    best: dict[int, tuple[int, str]] = {}
    for row in packet.get("Value") or []:
        if not isinstance(row, dict):
            continue
        try:
            sport_id = int(row["I"])
        except (KeyError, TypeError, ValueError):
            continue
        if sport_id in cfg.skip_sport_ids:
            continue
        if cfg.only_sport_ids and sport_id not in cfg.only_sport_ids:
            continue
        try:
            count = int(row.get("C") or 0)
        except (TypeError, ValueError):
            count = 0
        name = str(row.get("N") or row.get("R") or sport_id)
        prev = best.get(sport_id)
        if prev is None or count > prev[0]:
            best[sport_id] = (count, name)
    return [
        (sport_id, count, name)
        for sport_id, (count, name) in sorted(
            best.items(), key=lambda item: -item[1][0]
        )
        if count > 0
    ]


def _champ_ids(cfg: LxbetLineConfig, sport_id: int) -> list[int]:
    packet = fetch_packet(cfg.champs_list_url(sport_id), timeout=cfg.timeout)
    ids: list[int] = []
    seen: set[int] = set()
    for row in packet.get("Value") or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("LI")
        try:
            champ_id = int(raw)
        except (TypeError, ValueError):
            continue
        if champ_id in seen:
            continue
        seen.add(champ_id)
        ids.append(champ_id)
    return ids


def _safe_fetch(url: str, *, timeout: float) -> dict[str, Any] | None:
    try:
        return fetch_packet(url, timeout=timeout)
    except Exception as exc:
        logger.warning("1xBet line skip failed URL %s: %s", url, exc)
        return None


def _fetch_sport_events(
    cfg: LxbetLineConfig,
    sport_id: int,
    expected_count: int,
) -> list[dict[str, Any]]:
    """Fetch one sport; expand via championships when API 50-cap truncates."""
    cap = int(cfg.sport_count)
    sport_packet = _safe_fetch(cfg.sport_events_url(sport_id), timeout=cfg.timeout)
    events: list[dict[str, Any]] = []
    if sport_packet and isinstance(sport_packet.get("Value"), list):
        events = [e for e in sport_packet["Value"] if isinstance(e, dict)]

    need_champs = expected_count > cap and len(events) >= cap
    if not need_champs:
        return events

    try:
        champ_ids = _champ_ids(cfg, sport_id)
    except Exception as exc:
        logger.warning(
            "1xBet line champs list failed for sport=%s: %s", sport_id, exc
        )
        return events

    packets: list[dict[str, Any]] = []
    if sport_packet:
        packets.append(sport_packet)

    def _one(champ_id: int) -> dict[str, Any] | None:
        return _safe_fetch(cfg.champ_events_url(champ_id), timeout=cfg.timeout)

    # Champ expansion is heavy; with workers=1 stay fully sequential.
    champ_workers = max(1, min(2, cfg.max_workers))
    if champ_workers == 1:
        for champ_id in champ_ids:
            packet = _one(champ_id)
            if packet is not None:
                packets.append(packet)
    else:
        with ThreadPoolExecutor(max_workers=champ_workers) as pool:
            futures = [pool.submit(_one, champ_id) for champ_id in champ_ids]
            for fut in as_completed(futures):
                packet = fut.result()
                if packet is not None:
                    packets.append(packet)

    merged = merge_packets(*packets)
    value = merged.get("Value")
    return value if isinstance(value, list) else events


def fetch_snapshot(config: LxbetLineConfig | None = None) -> SnapshotResult:
    """
    Full line catalog when fetch_all_sports=true:

    1. GetSportsShortZip
    2. Per sport Get1x2_VZip?sports=ID&count=50
    3. If truncated vs catalog count, also GetChampsZip + per-champ Get1x2_VZip
    4. Merge + optional top list
    """
    cfg = config or LxbetLineConfig.from_env()
    _configure_client(cfg)

    if not cfg.fetch_all_sports:
        logger.info("Fetching 1xBet line snapshot: %s", cfg.snapshot_url())
        main = fetch_packet(cfg.snapshot_url(), timeout=cfg.timeout)
        packet = main
        if cfg.fetch_top:
            try:
                top = fetch_packet(cfg.top_url(), timeout=cfg.timeout)
                packet = merge_packets(main, top)
            except Exception as exc:
                logger.warning(
                    "1xBet line top fetch failed, using main only: %s", exc
                )
        fetched = len(packet.get("Value") or [])
        return SnapshotResult(
            packet=packet, expected_events=fetched, fetched_events=fetched
        )

    logger.info("Fetching 1xBet sports catalog: %s", cfg.sports_list_url())
    sports = _sport_catalog(cfg)
    expected = sum(count for _, count, _ in sports)
    logger.info(
        "1xBet line sports with events: %s (only=%s skip=%s)",
        len(sports),
        sorted(cfg.only_sport_ids) if cfg.only_sport_ids else "all",
        sorted(cfg.skip_sport_ids) if cfg.skip_sport_ids else [],
    )

    packets: list[dict[str, Any]] = []

    def _sport_job(item: tuple[int, int, str]) -> dict[str, Any]:
        sport_id, sport_expected, name = item
        events = _fetch_sport_events(cfg, sport_id, sport_expected)
        logger.info(
            "sport %s (%s): got %s events (catalog %s)",
            sport_id,
            name,
            len(events),
            sport_expected,
        )
        return {"Success": True, "Value": events}

    # One sport at a time when max_workers=1 (recommended for flaky mirrors).
    sport_workers = max(1, min(2, cfg.max_workers))
    if sport_workers == 1:
        for item in sports:
            try:
                packets.append(_sport_job(item))
            except Exception as exc:
                logger.warning("1xBet line sport worker failed: %s", exc)
    else:
        with ThreadPoolExecutor(max_workers=sport_workers) as pool:
            futures = [pool.submit(_sport_job, item) for item in sports]
            for fut in as_completed(futures):
                try:
                    packets.append(fut.result())
                except Exception as exc:
                    logger.warning("1xBet line sport worker failed: %s", exc)

    if cfg.fetch_top:
        try:
            logger.info("Fetching 1xBet line top: %s", cfg.top_url())
            packets.append(fetch_packet(cfg.top_url(), timeout=cfg.timeout))
        except Exception as exc:
            logger.warning("1xBet line top fetch failed: %s", exc)

    if not packets:
        raise LxbetLineApiError("No 1xBet line packets fetched")
    merged = merge_packets(*packets)
    fetched = len(merged.get("Value") or [])
    coverage = (fetched / expected) if expected else 1.0
    logger.info(
        "1xBet line merged events: %s (catalog %s, coverage=%.0f%%)",
        fetched,
        expected,
        coverage * 100,
    )
    return SnapshotResult(
        packet=merged, expected_events=expected, fetched_events=fetched
    )


def packet_version(packet: dict[str, Any]) -> int:
    """Use max event U (update time) when present, else Id."""
    value = packet.get("Value")
    if isinstance(value, list):
        versions: list[int] = []
        for event in value:
            if not isinstance(event, dict):
                continue
            raw = event.get("U")
            if raw is None:
                continue
            try:
                versions.append(int(raw))
            except (TypeError, ValueError):
                continue
        if versions:
            return max(versions)
    raw_id = packet.get("Id")
    if raw_id is not None:
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            pass
    return 0
