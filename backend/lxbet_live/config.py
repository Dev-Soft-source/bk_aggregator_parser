"""1xBet live (LiveFeed/Get1x2_VZip) HTTP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_EVENTS_URL = (
    "https://1xlite-55157.pro/service-api/LiveFeed/Get1x2_VZip"
)
DEFAULT_SPORTS_URL = (
    "https://1xlite-55157.pro/service-api/LiveFeed/GetSportsShortZip"
)
DEFAULT_CHAMPS_URL = (
    "https://1xlite-55157.pro/service-api/LiveFeed/GetChampsZip"
)
# API hard-caps each Get1x2_VZip response around this size.
DEFAULT_SPORT_COUNT = "50"
DEFAULT_TOP_COUNT = "10"
DEFAULT_LNG = "en"
DEFAULT_MODE = "4"
DEFAULT_COUNTRY = "179"
DEFAULT_GR = "1197"
DEFAULT_VIRTUAL_SPORTS = "true"
DEFAULT_NO_FILTER_BLOCK = "true"
# Full catalog (like lxbet_line): sports + champs in one cycle, then wait.
DEFAULT_POLL_INTERVAL = 10.0
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_WORKERS = 1
DEFAULT_REQUEST_PAUSE_SECONDS = 0.5
DEFAULT_FETCH_ALL_SPORTS = True
DEFAULT_FETCH_TOP = True
DEFAULT_SKIP_SPORT_IDS = "314,176"
# Empty = every live sport in GetSportsShortZip (same idea as full line catalog).
DEFAULT_ONLY_SPORT_IDS = ""
DEFAULT_SITE_NAME = "1xbet.com"
DEFAULT_PRUNE_COVERAGE_MIN = 0.9

OTHER_BOOKMAKER_SITES = frozenset(
    {
        "fonbet.com",
        "bet365.com",
        "ligastavok.ru",
        "betcity.ru",
        "betcity",
        "betcity.",
    }
)


def normalize_site_name(name: str | None) -> str:
    raw = (name or "").strip() or DEFAULT_SITE_NAME
    if raw in OTHER_BOOKMAKER_SITES or raw.lower() in OTHER_BOOKMAKER_SITES:
        return DEFAULT_SITE_NAME
    if raw.lower() in {"1xbet", "lxbet", "lxbet.com"}:
        return DEFAULT_SITE_NAME
    return raw


def _env_bool_str(key: str, default: str) -> str:
    raw = os.getenv(key, default).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "true"
    if raw in {"0", "false", "no", "off"}:
        return "false"
    return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_id_set(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class LxbetLiveConfig:
    events_url: str
    sports_url: str
    champs_url: str
    sport_count: str
    top_count: str
    lng: str
    mode: str
    country: str
    gr: str
    virtual_sports: str
    no_filter_block_event: str
    fetch_all_sports: bool
    fetch_top: bool
    max_workers: int
    skip_sport_ids: frozenset[int]
    only_sport_ids: frozenset[int]
    prune_coverage_min: float
    poll_interval: float
    timeout: float
    request_pause_seconds: float = DEFAULT_REQUEST_PAUSE_SECONDS
    site_name: str = DEFAULT_SITE_NAME

    @classmethod
    def from_env(cls) -> "LxbetLiveConfig":
        events_url = (
            os.getenv("LXBET_LIVE_EVENTS_URL") or DEFAULT_EVENTS_URL
        ).strip() or DEFAULT_EVENTS_URL
        sport_count = (
            os.getenv("LXBET_LIVE_SPORT_COUNT") or DEFAULT_SPORT_COUNT
        ).strip() or DEFAULT_SPORT_COUNT
        only_raw = os.getenv("LXBET_LIVE_ONLY_SPORT_IDS", DEFAULT_ONLY_SPORT_IDS)
        skip_raw = os.getenv("LXBET_LIVE_SKIP_SPORT_IDS", DEFAULT_SKIP_SPORT_IDS)
        return cls(
            events_url=events_url,
            sports_url=(
                os.getenv("LXBET_LIVE_SPORTS_URL", DEFAULT_SPORTS_URL).strip()
                or DEFAULT_SPORTS_URL
            ),
            champs_url=(
                os.getenv("LXBET_LIVE_CHAMPS_URL", DEFAULT_CHAMPS_URL).strip()
                or DEFAULT_CHAMPS_URL
            ),
            sport_count=sport_count,
            top_count=os.getenv("LXBET_LIVE_TOP_COUNT", DEFAULT_TOP_COUNT).strip()
            or DEFAULT_TOP_COUNT,
            lng=os.getenv("LXBET_LIVE_LNG", DEFAULT_LNG).strip() or DEFAULT_LNG,
            mode=os.getenv("LXBET_LIVE_MODE", DEFAULT_MODE).strip() or DEFAULT_MODE,
            country=os.getenv("LXBET_LIVE_COUNTRY", DEFAULT_COUNTRY).strip()
            or DEFAULT_COUNTRY,
            gr=os.getenv("LXBET_LIVE_GR", DEFAULT_GR).strip() or DEFAULT_GR,
            virtual_sports=_env_bool_str(
                "LXBET_LIVE_VIRTUAL_SPORTS", DEFAULT_VIRTUAL_SPORTS
            ),
            no_filter_block_event=_env_bool_str(
                "LXBET_LIVE_NO_FILTER_BLOCK_EVENT", DEFAULT_NO_FILTER_BLOCK
            ),
            fetch_all_sports=_env_bool(
                "LXBET_LIVE_FETCH_ALL_SPORTS", DEFAULT_FETCH_ALL_SPORTS
            ),
            fetch_top=_env_bool("LXBET_LIVE_FETCH_TOP", DEFAULT_FETCH_TOP),
            max_workers=max(
                1,
                int(os.getenv("LXBET_LIVE_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))),
            ),
            skip_sport_ids=_parse_id_set(skip_raw),
            only_sport_ids=_parse_id_set(only_raw) if only_raw.strip() else frozenset(),
            prune_coverage_min=float(
                os.getenv(
                    "LXBET_LIVE_PRUNE_COVERAGE_MIN",
                    str(DEFAULT_PRUNE_COVERAGE_MIN),
                )
            ),
            poll_interval=float(
                os.getenv(
                    "LXBET_LIVE_POLL_INTERVAL_SECONDS",
                    str(DEFAULT_POLL_INTERVAL),
                )
            ),
            timeout=float(os.getenv("LXBET_LIVE_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT))),
            request_pause_seconds=max(
                0.0,
                float(
                    os.getenv(
                        "LXBET_LIVE_REQUEST_PAUSE_SECONDS",
                        str(DEFAULT_REQUEST_PAUSE_SECONDS),
                    )
                ),
            ),
            site_name=normalize_site_name(
                os.getenv("LXBET_LIVE_SITE_NAME") or DEFAULT_SITE_NAME
            ),
        )

    def _build_url(self, base: str, ordered_query: list[tuple[str, str]]) -> str:
        parsed = urlparse(base)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(ordered_query),
                parsed.fragment,
            )
        )

    def _common_tail(self) -> list[tuple[str, str]]:
        return [
            ("lng", self.lng),
            ("gr", self.gr),
            ("mode", self.mode),
            ("country", self.country),
            ("virtualSports", self.virtual_sports),
            ("noFilterBlockEvent", self.no_filter_block_event),
        ]

    def sports_list_url(self) -> str:
        return self._build_url(
            self.sports_url,
            [
                ("lng", self.lng),
                ("gr", self.gr),
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
                ("groupChamps", "true"),
            ],
        )

    def champs_list_url(self, sport_id: int) -> str:
        return self._build_url(
            self.champs_url,
            [
                ("sport", str(int(sport_id))),
                ("lng", self.lng),
                ("gr", self.gr),
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
            ],
        )

    def sport_events_url(self, sport_id: int) -> str:
        return self._build_url(
            self.events_url,
            [
                ("sports", str(int(sport_id))),
                ("count", self.sport_count),
                *self._common_tail(),
            ],
        )

    def champ_events_url(self, champ_id: int) -> str:
        return self._build_url(
            self.events_url,
            [
                ("champs", str(int(champ_id))),
                ("count", self.sport_count),
                *self._common_tail(),
            ],
        )

    def snapshot_url(self) -> str:
        """Single-list URL when fetch_all_sports=false (matches site count=40)."""
        return self._build_url(
            self.events_url,
            [
                ("count", self.sport_count),
                *self._common_tail(),
            ],
        )

    def top_url(self) -> str:
        return self._build_url(
            self.events_url,
            [
                ("count", self.top_count),
                ("lng", self.lng),
                ("gr", self.gr),
                ("mode", self.mode),
                ("country", self.country),
                ("top", "true"),
                ("virtualSports", self.virtual_sports),
                ("noFilterBlockEvent", self.no_filter_block_event),
            ],
        )
