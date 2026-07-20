"""Bet365 line hub URL helpers (Asian Odds / all sports lists)."""

from __future__ import annotations

import os
import re

# #/AO/ = Asian Odds shell
# #/AS/B{n}/ = sport list (ZAP match odds for that class)
# #/AC/ = competition / coupon views
_LINE_HUB_TOKENS: tuple[str, ...] = ("#/AO/", "#/AS/", "#/AC/")

# Default sport class ids used on #/AS/B{n}/ (bet365 CL / B n).
# B1 Soccer is always included; expand for full line coverage.
DEFAULT_SPORT_CLASS_IDS: tuple[int, ...] = (
    1,   # Soccer / Football
    13,  # Tennis
    18,  # Basketball
    16,  # Baseball
    91,  # Esports
    78,  # Table Tennis (common)
    17,  # Ice Hockey
    12,  # American Football
    8,   # Handball
    9,   # Rugby Union
    14,  # Snooker
    15,  # Cricket
    3,   # Golf
    36,  # Darts
    83,  # MMA / UFC (common)
)

# Multilingual sport tab labels on #/AO/ (Romanian / English / Spanish …)
SPORT_TAB_LABELS: tuple[str, ...] = (
    "Fotbal",
    "Soccer",
    "Football",
    "Futbol",
    "Tenis",
    "Tennis",
    "Baschet",
    "Basketball",
    "Baloncesto",
    "Baseball",
    "Beisbol",
    "Sporturi electronice",
    "Esports",
    "E-Sports",
    "Darts",
    "Sageti",
    "Handbal",
    "Handball",
    "Hochei pe gheata",
    "Ice Hockey",
    "Hockey",
    "Cricket",
    "Golf",
    "Rugby",
    "Snooker",
    "MMA",
    "UFC",
    "Volleyball",
    "Volei",
)

DEFAULT_FOOTBALL_URL = "https://www.bet365.com/#/AS/B1/"


def is_line_hub_url(url: str) -> bool:
    """True when Chrome is on a prematch / Asian Odds line route."""
    return any(token in (url or "") for token in _LINE_HUB_TOKENS)


def is_sport_list_url(url: str) -> bool:
    """True on any #/AS/B{n}/ sports list (any sport, not only football)."""
    return bool(re.search(r"#/AS/B\d+", url or ""))


def is_football_line_url(url: str) -> bool:
    """True on football (B1) sports list."""
    text = url or ""
    return "#/AS/B1/" in text or text.rstrip("/").endswith("#/AS/B1")


def sport_list_url(sport_class_id: int) -> str:
    return f"https://www.bet365.com/#/AS/B{int(sport_class_id)}/"


def sport_class_ids_from_env() -> tuple[int, ...]:
    """
    BET365_LINE_SPORT_IDS=1,13,18,16,91
    Empty / unset → DEFAULT_SPORT_CLASS_IDS (all common line sports).
    """
    raw = os.getenv("BET365_LINE_SPORT_IDS", "").strip()
    if not raw:
        return DEFAULT_SPORT_CLASS_IDS
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return tuple(ids) if ids else DEFAULT_SPORT_CLASS_IDS
