"""Shared bookmaker adapter contracts (TZ §6.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable


class ChangeType(str, Enum):
    FIXTURE = "fixture"
    SCORE = "score"
    BETTING_STATUS = "betting_status"
    ODDS = "odds"


@dataclass(frozen=True)
class SportRef:
    payload_id: int
    name: str
    alias: str | None = None
    sort_order: str | None = None


@dataclass(frozen=True)
class TournamentRef:
    payload_id: int
    sport_payload_id: int
    name: str
    country_name: str | None = None
    region_id: int | None = None


@dataclass(frozen=True)
class EventRef:
    payload_id: int
    sport_payload_id: int
    league_payload_id: int
    team1: str | None
    team2: str | None
    start_time_unix: int | None
    place: str
    team1_id: int | None = None
    team2_id: int | None = None
    priority: int | None = None


@dataclass(frozen=True)
class OddsOutcome:
    factor_id: int
    odds: float
    line_param: int | None = None
    line_param_raw: int | None = None
    line_param_text: str | None = None
    is_handicap_total: bool = False


@dataclass(frozen=True)
class OddsMarket:
    market_event_id: int
    market_event_name: str | None
    outcomes: tuple[OddsOutcome, ...]


@dataclass
class Change:
    change_type: ChangeType
    match_payload_id: int
    packet_version: int
    from_version: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthStatus:
    ok: bool
    code: str
    message: str
    last_success_at: datetime | None = None
    last_packet_version: int | None = None
    last_error: str | None = None
    poll_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class PacketSummary:
    packet_version: int
    from_version: int | None
    is_snapshot: bool
    sports: int
    leagues: int
    fixtures: int
    score_changes: int
    betting_status_changes: int
    odds_markets: int
    odds_outcomes: int


@runtime_checkable
class BookmakerAdapter(Protocol):
    code: str
    display_name: str

    def discover_sports(self, packet: dict[str, Any]) -> list[SportRef]: ...

    def discover_tournaments(self, packet: dict[str, Any]) -> list[TournamentRef]: ...

    def discover_events(
        self, packet: dict[str, Any], mode: str = "live"
    ) -> list[EventRef]: ...

    def map_packet_to_changes(
        self,
        packet: dict[str, Any],
        *,
        known_match_ids: set[int] | None = None,
    ) -> list[Change]: ...

    def packet_summary(
        self,
        packet: dict[str, Any],
        *,
        known_match_ids: set[int] | None = None,
    ) -> PacketSummary: ...

    def stream_live_changes(
        self,
        *,
        max_iterations: int | None = None,
    ) -> Iterator[tuple[dict[str, Any], list[Change], PacketSummary]]: ...

    def health(self) -> HealthStatus: ...
