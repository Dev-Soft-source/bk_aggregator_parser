"""HTTP event catalog for Betcity (team / league / sport names)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from betcity_live.config import BetcityConfig

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = "https://ad.betcity.ru/d/on_air/events"
DEFAULT_REFRESH_SECONDS = 30.0


@dataclass(frozen=True)
class CatalogEvent:
    event_id: int
    sport_id: int | None = None
    sport_name: str | None = None
    championship_id: int | None = None
    league_name: str | None = None
    team1: str | None = None
    team2: str | None = None
    start_time_unix: int | None = None
    score1: int | None = None
    score2: int | None = None
    raw_scores: dict[str, Any] | None = None
    minute: int | None = None
    status_ev: int | None = None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_score_pair(value: Any) -> tuple[int | None, int | None]:
    """Parse Betcity score from sc_ev ('1:2') or sc_ev_cmx.main[0]."""
    if isinstance(value, dict):
        main = value.get("main")
        if isinstance(main, list) and main:
            first = main[0]
            if isinstance(first, list) and len(first) >= 2:
                try:
                    return int(first[0]), int(first[1])
                except (TypeError, ValueError):
                    return None, None
        return None, None
    if isinstance(value, str) and ":" in value:
        left, right = value.split(":", 1)
        try:
            return int(left.strip()), int(right.strip())
        except ValueError:
            return None, None
    return None, None


def parse_catalog_payload(payload: dict[str, Any]) -> dict[int, CatalogEvent]:
    """Parse ad.betcity.ru on-air/off events JSON into event_id → CatalogEvent."""
    reply = payload.get("reply")
    if not isinstance(reply, dict):
        return {}
    sports = reply.get("sports")
    if not isinstance(sports, dict):
        return {}

    out: dict[int, CatalogEvent] = {}
    for sport_key, sport in sports.items():
        if not isinstance(sport, dict):
            continue
        sport_id = _as_int(sport.get("id_sp") or sport_key)
        sport_name = _as_str(sport.get("name_sp"))
        championships = sport.get("chmps") or {}
        if not isinstance(championships, dict):
            continue
        for ch_key, chmp in championships.items():
            if not isinstance(chmp, dict):
                continue
            championship_id = _as_int(chmp.get("id_ch") or ch_key)
            league_name = _as_str(chmp.get("name_ch"))
            events = chmp.get("evts") or {}
            if not isinstance(events, dict):
                continue
            for ev_key, event in events.items():
                if not isinstance(event, dict):
                    continue
                event_id = _as_int(event.get("id_ev") or ev_key)
                if event_id is None:
                    continue
                cmx = event.get("sc_ev_cmx")
                score1, score2 = _parse_score_pair(cmx)
                if score1 is None and score2 is None:
                    score1, score2 = _parse_score_pair(event.get("sc_ev"))
                raw_scores = cmx if isinstance(cmx, dict) else None
                out[event_id] = CatalogEvent(
                    event_id=event_id,
                    sport_id=sport_id,
                    sport_name=sport_name,
                    championship_id=championship_id,
                    league_name=league_name,
                    team1=_as_str(event.get("name_ht")),
                    team2=_as_str(event.get("name_at")),
                    start_time_unix=_as_int(event.get("date_ev")),
                    score1=score1,
                    score2=score2,
                    raw_scores=raw_scores,
                    minute=_as_int(event.get("min")),
                    status_ev=_as_int(event.get("status_ev")),
                )
    return out


class BetcityCatalog:
    """Cached HTTP catalog used to enrich live WS fixtures with names."""

    def __init__(
        self,
        config: BetcityConfig,
        *,
        catalog_url: str | None = None,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._catalog_url = (
            (catalog_url or "").strip()
            or config.catalog_url
            or DEFAULT_CATALOG_URL
        )
        self._refresh_seconds = refresh_seconds
        self._session = session or requests.Session()
        proxies = config.requests_proxies()
        if proxies and session is None:
            self._session.proxies.update(proxies)
        self._events: dict[int, CatalogEvent] = {}
        self._fetched_at: float | None = None
        self._last_error: str | None = None

    @property
    def size(self) -> int:
        return len(self._events)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get(self, event_id: int) -> CatalogEvent | None:
        return self._events.get(event_id)

    @property
    def event_ids(self) -> set[int]:
        return set(self._events.keys())

    def ensure_fresh(self, *, force: bool = False) -> bool:
        now = time.time()
        if (
            not force
            and self._fetched_at is not None
            and (now - self._fetched_at) < self._refresh_seconds
        ):
            return False
        return self.refresh()

    def refresh(self) -> bool:
        headers = {
            "User-Agent": self._config.user_agent,
            "Origin": self._config.origin,
            "Referer": self._config.referer,
            "Accept": "application/json,text/plain,*/*",
        }
        if self._config.cookie:
            headers["Cookie"] = self._config.cookie
        try:
            resp = self._session.get(
                self._catalog_url,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise ValueError("catalog response is not a JSON object")
            events = parse_catalog_payload(payload)
            self._events = events
            self._fetched_at = time.time()
            self._last_error = None
            logger.info(
                "Betcity catalog refreshed: %s events from %s",
                len(events),
                self._catalog_url,
            )
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Betcity catalog refresh failed: %s", exc)
            return False
