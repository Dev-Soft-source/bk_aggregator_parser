"""Fonbet bookmaker: API client, parser adapter, PostgreSQL importer."""

from fonbet.api import (
    FonbetApiError,
    fetch_list,
    fetch_list_light,
    fetch_packet,
    is_snapshot_packet,
    packet_version,
)
from fonbet.config import FonbetApiConfig

__all__ = [
    "FonbetAdapter",
    "FonbetApiConfig",
    "FonbetApiError",
    "fetch_list",
    "fetch_list_light",
    "fetch_packet",
    "import_packet",
    "is_snapshot_packet",
    "load_packet",
    "packet_version",
]


def __getattr__(name: str):
    if name == "FonbetAdapter":
        from fonbet.adapter import FonbetAdapter

        return FonbetAdapter
    if name == "import_packet":
        from fonbet.importer import import_packet

        return import_packet
    if name == "load_packet":
        from fonbet.importer import load_packet

        return load_packet
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
