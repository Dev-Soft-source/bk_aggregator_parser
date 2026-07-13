"""1xBet line (LineFeed/Get1x2_VZip) HTTP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_EVENTS_URL = (
    "https://1xlite-55157.pro/service-api/LineFeed/Get1x2_VZip"
)
DEFAULT_SPORTS_URL = (
    "https://1xlite-55157.pro/service-api/LineFeed/GetSportsShortZip"
)
DEFAULT_CHAMPS_URL = (
    "https://1xlite-55157.pro/service-api/LineFeed/GetChampsZip"
)
# API hard-caps each Get1x2_VZip response around this size.
DEFAULT_SPORT_COUNT = "50"
DEFAULT_TOP_COUNT = "10"
DEFAULT_LNG = "en"
DEFAULT_MODE = "4"
DEFAULT_COUNTRY = "179"
DEFAULT_VIRTUAL_SPORTS = "true"
# Full catalog needs many HTTP calls; keep concurrency low to avoid TLS drops.
DEFAULT_POLL_INTERVAL = 90.0
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_WORKERS = 1
DEFAULT_REQUEST_PAUSE_SECONDS = 1.0
# Polybet/Weather inflate catalog counts but usually return empty lists.
DEFAULT_SKIP_SPORT_IDS = "314,176"
DEFAULT_SITE_NAME = "1xbet.com"
# Only delete missing matches when this fraction of catalog events was fetched.
DEFAULT_PRUNE_COVERAGE_MIN = 0.9
# Drop line matches whose kickoff is older than this many hours.
DEFAULT_PRUNE_PAST_HOURS = 48

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


@dataclass(frozen=True)
class LxbetLineConfig:
    events_url: str
    sports_url: str
    champs_url: str
    sport_count: str
    top_count: str
    lng: str
    mode: str
    country: str
    virtual_sports: str
    fetch_all_sports: bool
    fetch_top: bool
    max_workers: int
    skip_sport_ids: frozenset[int]
    only_sport_ids: frozenset[int]
    prune_coverage_min: float
    prune_past_hours: int
    poll_interval: float
    timeout: float
    request_pause_seconds: float = DEFAULT_REQUEST_PAUSE_SECONDS
    site_name: str = DEFAULT_SITE_NAME

    @classmethod
    def from_env(cls) -> "LxbetLineConfig":
        # Back-compat: LXBET_LINE_URL / LXBET_LINE_COUNT still accepted.
        events_url = (
            os.getenv("LXBET_LINE_EVENTS_URL")
            or os.getenv("LXBET_LINE_URL")
            or DEFAULT_EVENTS_URL
        ).strip() or DEFAULT_EVENTS_URL
        sport_count = (
            os.getenv("LXBET_LINE_SPORT_COUNT")
            or os.getenv("LXBET_LINE_COUNT")
            or DEFAULT_SPORT_COUNT
        ).strip() or DEFAULT_SPORT_COUNT
        skip_raw = os.getenv("LXBET_LINE_SKIP_SPORT_IDS", DEFAULT_SKIP_SPORT_IDS)
        skip_ids: set[int] = set()
        for part in skip_raw.split(","):
            part = part.strip()
            if part:
                skip_ids.add(int(part))
        only_raw = os.getenv("LXBET_LINE_ONLY_SPORT_IDS", "").strip()
        only_ids: set[int] = set()
        if only_raw:
            for part in only_raw.split(","):
                part = part.strip()
                if part:
                    only_ids.add(int(part))
        return cls(
            events_url=events_url,
            sports_url=(
                os.getenv("LXBET_LINE_SPORTS_URL", DEFAULT_SPORTS_URL).strip()
                or DEFAULT_SPORTS_URL
            ),
            champs_url=(
                os.getenv("LXBET_LINE_CHAMPS_URL", DEFAULT_CHAMPS_URL).strip()
                or DEFAULT_CHAMPS_URL
            ),
            sport_count=sport_count,
            top_count=os.getenv("LXBET_LINE_TOP_COUNT", DEFAULT_TOP_COUNT).strip()
            or DEFAULT_TOP_COUNT,
            lng=os.getenv("LXBET_LINE_LNG", DEFAULT_LNG).strip() or DEFAULT_LNG,
            mode=os.getenv("LXBET_LINE_MODE", DEFAULT_MODE).strip() or DEFAULT_MODE,
            country=os.getenv("LXBET_LINE_COUNTRY", DEFAULT_COUNTRY).strip()
            or DEFAULT_COUNTRY,
            virtual_sports=_env_bool_str(
                "LXBET_LINE_VIRTUAL_SPORTS", DEFAULT_VIRTUAL_SPORTS
            ),
            fetch_all_sports=_env_bool("LXBET_LINE_FETCH_ALL_SPORTS", True),
            fetch_top=_env_bool("LXBET_LINE_FETCH_TOP", True),
            max_workers=max(
                1,
                int(os.getenv("LXBET_LINE_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))),
            ),
            skip_sport_ids=frozenset(skip_ids),
            only_sport_ids=frozenset(only_ids),
            prune_coverage_min=float(
                os.getenv(
                    "LXBET_LINE_PRUNE_COVERAGE_MIN",
                    str(DEFAULT_PRUNE_COVERAGE_MIN),
                )
            ),
            prune_past_hours=max(
                0,
                int(
                    os.getenv(
                        "LXBET_LINE_PRUNE_PAST_HOURS",
                        str(DEFAULT_PRUNE_PAST_HOURS),
                    )
                ),
            ),
            poll_interval=float(
                os.getenv(
                    "LXBET_LINE_POLL_INTERVAL_SECONDS",
                    str(DEFAULT_POLL_INTERVAL),
                )
            ),
            timeout=float(os.getenv("LXBET_LINE_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT))),
            request_pause_seconds=max(
                0.0,
                float(
                    os.getenv(
                        "LXBET_LINE_REQUEST_PAUSE_SECONDS",
                        str(DEFAULT_REQUEST_PAUSE_SECONDS),
                    )
                ),
            ),
            site_name=normalize_site_name(
                os.getenv("LXBET_LINE_SITE_NAME") or DEFAULT_SITE_NAME
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

    def sports_list_url(self) -> str:
        return self._build_url(
            self.sports_url,
            [
                ("lng", self.lng),
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
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
            ],
        )

    def sport_events_url(self, sport_id: int) -> str:
        # sports= must lead; count is hard-capped by API (~50).
        return self._build_url(
            self.events_url,
            [
                ("sports", str(int(sport_id))),
                ("count", self.sport_count),
                ("lng", self.lng),
                ("mode", self.mode),
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
            ],
        )

    def champ_events_url(self, champ_id: int) -> str:
        return self._build_url(
            self.events_url,
            [
                ("champs", str(int(champ_id))),
                ("count", self.sport_count),
                ("lng", self.lng),
                ("mode", self.mode),
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
            ],
        )

    def snapshot_url(self) -> str:
        """Legacy single-list URL (count-first) used when fetch_all_sports=false."""
        return self._build_url(
            self.events_url,
            [
                ("count", self.sport_count),
                ("lng", self.lng),
                ("mode", self.mode),
                ("country", self.country),
                ("virtualSports", self.virtual_sports),
            ],
        )

    def top_url(self) -> str:
        return self._build_url(
            self.events_url,
            [
                ("count", self.top_count),
                ("lng", self.lng),
                ("mode", self.mode),
                ("country", self.country),
                ("top", "true"),
                ("virtualSports", self.virtual_sports),
            ],
        )
