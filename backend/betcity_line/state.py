"""Incremental Betcity prematch state from /d/off/events JSON packets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if (
            key in dst
            and isinstance(dst[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst


@dataclass
class LineEvent:
    event_id: int
    sport_id: int | None = None
    sport_name: str | None = None
    championship_id: int | None = None
    league_name: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class BetcityLineState:
    """Accumulates sports tree from full snapshot + md deltas."""

    events: dict[int, LineEvent] = field(default_factory=dict)
    last_ntime: int | None = None
    packet_count: int = 0

    def clear(self) -> None:
        self.events.clear()

    def retain_only(self, keep_ids: set[int]) -> int:
        if not keep_ids:
            return 0
        before = len(self.events)
        self.events = {
            event_id: event
            for event_id, event in self.events.items()
            if event_id in keep_ids
        }
        return before - len(self.events)

    def apply_packet(self, packet: dict[str, Any], *, replace: bool = False) -> None:
        self.packet_count += 1
        reply = packet.get("reply")
        if not isinstance(reply, dict):
            return

        ntime = reply.get("ntime")
        if ntime is not None:
            try:
                self.last_ntime = int(ntime)
            except (TypeError, ValueError):
                pass

        sports = reply.get("sports")
        if not isinstance(sports, dict):
            return

        if replace:
            self.events.clear()

        for sport_key, sport in sports.items():
            if not isinstance(sport, dict):
                continue
            try:
                sport_id = int(sport.get("id_sp") or sport_key)
            except (TypeError, ValueError):
                continue
            sport_name = sport.get("name_sp")
            championships = sport.get("chmps") or {}
            if not isinstance(championships, dict):
                continue
            for ch_key, chmp in championships.items():
                if not isinstance(chmp, dict):
                    continue
                try:
                    championship_id = int(chmp.get("id_ch") or ch_key)
                except (TypeError, ValueError):
                    continue
                league_name = chmp.get("name_ch")
                events = chmp.get("evts") or {}
                if not isinstance(events, dict):
                    continue
                for ev_key, event in events.items():
                    if not isinstance(event, dict):
                        continue
                    try:
                        event_id = int(event.get("id_ev") or ev_key)
                    except (TypeError, ValueError):
                        continue
                    if event.get("del") or event.get("del_ev"):
                        self.events.pop(event_id, None)
                        continue
                    state = self.events.get(event_id)
                    if state is None:
                        state = LineEvent(
                            event_id=event_id,
                            sport_id=sport_id,
                            sport_name=str(sport_name) if sport_name else None,
                            championship_id=championship_id,
                            league_name=str(league_name) if league_name else None,
                        )
                        self.events[event_id] = state
                    else:
                        state.sport_id = sport_id
                        if sport_name:
                            state.sport_name = str(sport_name)
                        state.championship_id = championship_id
                        if league_name:
                            state.league_name = str(league_name)
                    _deep_merge(state.fields, event)
