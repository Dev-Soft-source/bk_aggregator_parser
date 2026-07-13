"""Incremental Betcity live feed state from WebSocket JSON frames."""

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
class EventState:
    event_id: int
    sport_id: int | None = None
    championship_id: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    main_markets: dict[str, Any] = field(default_factory=dict)


@dataclass
class BetcityFeedState:
    """Accumulates sports + main odds deltas from sc.betcity.ru frames."""

    events: dict[int, EventState] = field(default_factory=dict)
    last_type: int | None = None
    last_md: int | None = None
    frame_count: int = 0

    def retain_only(self, keep_ids: set[int]) -> int:
        """Drop events not in keep_ids. Returns number removed."""
        if not keep_ids:
            return 0
        before = len(self.events)
        self.events = {
            event_id: event
            for event_id, event in self.events.items()
            if event_id in keep_ids
        }
        return before - len(self.events)

    def apply_frame(self, packet: dict[str, Any]) -> None:
        self.frame_count += 1
        if "type" in packet:
            try:
                self.last_type = int(packet["type"])
            except (TypeError, ValueError):
                pass
        if "md" in packet:
            try:
                self.last_md = int(packet["md"])
            except (TypeError, ValueError):
                pass

        reply = packet.get("reply")
        if not isinstance(reply, dict):
            return

        sports = reply.get("sports")
        if isinstance(sports, dict):
            self._apply_sports(sports)

        main = reply.get("main")
        if isinstance(main, dict):
            self._apply_main(main)

    def _apply_sports(self, sports: dict[str, Any]) -> None:
        for sport_key, sport in sports.items():
            if not isinstance(sport, dict):
                continue
            try:
                sport_id = int(sport.get("id_sp") or sport_key)
            except (TypeError, ValueError):
                continue
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
                    # Drop deleted events from live state.
                    if event.get("del") or event.get("del_ev"):
                        self.events.pop(event_id, None)
                        continue
                    state = self.events.get(event_id)
                    if state is None:
                        state = EventState(
                            event_id=event_id,
                            sport_id=sport_id,
                            championship_id=championship_id,
                        )
                        self.events[event_id] = state
                    else:
                        state.sport_id = sport_id
                        state.championship_id = championship_id
                    _deep_merge(state.fields, event)

    def _apply_main(self, main: dict[str, Any]) -> None:
        for ev_key, markets in main.items():
            if not isinstance(markets, dict):
                continue
            try:
                event_id = int(ev_key)
            except (TypeError, ValueError):
                continue
            state = self.events.get(event_id)
            if state is None:
                state = EventState(event_id=event_id)
                self.events[event_id] = state
            for market_key, market in markets.items():
                if not isinstance(market, dict):
                    continue
                existing = state.main_markets.get(str(market_key))
                if existing is None:
                    state.main_markets[str(market_key)] = dict(market)
                else:
                    _deep_merge(existing, market)
