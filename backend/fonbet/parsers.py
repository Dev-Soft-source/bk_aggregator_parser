from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Segment name prefixes that are product/tournament labels, not countries.
# Sport names themselves come from the API via build_sport_prefixes().
SEGMENT_LABEL_PREFIXES: frozenset[str] = frozenset(
    {
        "Soccer",
        "FC 24",
        "FC 26",
        "ITF",
        "ATP Challenger",
        "Setka Cup",
        "TT Cup",
        "NHL 26",
        "NBA 2K26",
        "Roland Garros",
        "Short-hockey",
        "Short Hockey",
        "Dota 2",
        "Counter-Strike",
        "Valorant",
        "BWF",
        "T20",
        "WC 2026",
        "Beach Pro Tour",
        "MiLB",
        "AHL",
    }
)


def build_sport_prefixes(sports: list[dict[str, Any]]) -> set[str]:
    """Build strip-prefixes from API sport entries plus known segment labels."""
    prefixes = set(SEGMENT_LABEL_PREFIXES)
    for item in sports:
        if item.get("kind") != "sport":
            continue
        prefixes.add(item["name"])
        alias = item.get("alias")
        if alias:
            prefixes.add(alias.replace("-", " ").title())
    return prefixes


def parse_country_and_league(
    segment_name: str,
    *,
    sport_prefixes: set[str],
    root_sport_name: str | None = None,
) -> tuple[str | None, str]:
    """
    Split a league segment name into (country, league).

  Examples:
        "Armenia. Premier League" -> ("Armenia", "Premier League")
        "Soccer. Belarus. Cup. 1/32 Finals" -> ("Belarus", "Cup. 1/32 Finals")
        "ITF. France. Open" -> ("France", "Open")
    """
    parts = [part.strip() for part in segment_name.split(". ") if part.strip()]
    if not parts:
        return None, segment_name

    strip = set(sport_prefixes)
    if root_sport_name:
        strip.add(root_sport_name)

    remainder = list(parts)
    while remainder and remainder[0] in strip:
        remainder = remainder[1:]

    if len(remainder) >= 2:
        return remainder[0], ". ".join(remainder[1:])
    if len(remainder) == 1:
        return None, remainder[0]
    return None, segment_name


def unix_to_datetime(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def event_year_from_start_time(
    start_time: datetime | None,
    fallback_year: int | None = None,
) -> int | None:
    if start_time is not None:
        return start_time.year
    return fallback_year


def millis_to_datetime(timestamp_ms: int | None) -> datetime | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def build_sports_maps(
    sports: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, int]]:
    """Index sports/segments and map league segment id -> root sport id."""
    by_id = {item["id"]: item for item in sports}
    league_to_sport: dict[int, int] = {}

    for item in sports:
        if item.get("kind") != "segment":
            continue
        sport_id = resolve_root_sport_id(item["id"], by_id)
        if sport_id is not None:
            league_to_sport[item["id"]] = sport_id

    return by_id, league_to_sport


def resolve_root_sport_id(
    segment_id: int,
    sports_by_id: dict[int, dict[str, Any]],
) -> int | None:
    """Walk parent chain until a top-level sport (kind=sport) is found."""
    current_id: int | None = segment_id
    visited: set[int] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        item = sports_by_id.get(current_id)
        if not item:
            return None
        if item.get("kind") == "sport":
            return current_id
        current_id = item.get("parentId")

    return None


def resolve_match_id_for_update(
    event_id: int,
    events_by_id: dict[int, dict[str, Any]],
    known_match_ids: set[int],
) -> int | None:
    """Map any event id (match or sub-market) to a root match id we store in the DB."""
    if event_id in known_match_ids:
        return event_id
    root_id = find_root_match_id(event_id, events_by_id)
    if root_id is not None and root_id in known_match_ids:
        return root_id
    return None


def find_root_match_id(event_id: int, events_by_id: dict[int, dict[str, Any]]) -> int | None:
    current_id = event_id
    visited: set[int] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        event = events_by_id.get(current_id)
        if not event:
            return None
        if event.get("level") == 1:
            return current_id
        current_id = event.get("parentId")

    return None


LINE_PARAM_SENTINEL = -2147483648


def normalize_line_param(value: int | None) -> int:
    return LINE_PARAM_SENTINEL if value is None else value


def is_handicap_or_total(factor: dict[str, Any]) -> bool:
    return "p" in factor or "pt" in factor
