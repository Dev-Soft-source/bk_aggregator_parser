"""In-memory bet365 ZAP feed state (events, markets, selections)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bet365.odds_config import (
    import_all_from_socket,
    main_market_id,
    skip_esoccer,
    soccer_class_id,
)
from bet365.zap_parse import (
    ZapMessage,
    field_int,
    fractional_to_decimal,
    merge_fields,
    parse_match_teams,
    parse_wire_chunk,
    sport_class_from_event_fields,
)


@dataclass
class SelectionState:
    it: str
    fi: int | None = None
    ma_id: int | None = None
    name: str | None = None
    order: int | None = None
    odds_frac: str | None = None
    odds_decimal: float | None = None
    suspended: bool = False
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketState:
    it: str
    fi: int | None = None
    market_id: int | None = None
    name: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventState:
    fi: int
    it: str | None = None
    name: str | None = None
    competition: str | None = None
    sport_class: int | None = None
    score: str | None = None
    minute: int | None = None
    timer_secs: int | None = None
    timer_ticking: bool | None = None
    timer_tu: str | None = None
    match_length: int | None = None  # ML — regulation minutes (soccer usually 90)
    live: bool = False
    team1: str | None = None
    team2: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


class ZapFeedState:
    def __init__(self) -> None:
        self.events: dict[int, EventState] = {}
        self.markets: dict[str, MarketState] = {}
        self.selections: dict[str, SelectionState] = {}
        self.sport_classes: dict[int, str] = {}
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def apply_chunk(self, chunk: str) -> None:
        _, message = parse_wire_chunk(chunk)
        if message is None:
            return
        self._frame_count += 1
        self._apply_message(message)

    def apply_body(self, body: str, *, path: str | None = None, op: str | None = None) -> None:
        from bet365.zap_parse import parse_message_body

        message = parse_message_body(body if body and body[0] in "FUID" else f"F|{body}")
        if message is None:
            return
        if op:
            message = ZapMessage(op=op, path=path, records=message.records)
        elif path:
            message = ZapMessage(op=message.op, path=path, records=message.records)
        self._frame_count += 1
        self._apply_message(message)

    def _apply_message(self, message: ZapMessage) -> None:
        if message.op in ("F", "I"):
            cursor_ev: EventState | None = None
            cursor_ma: MarketState | None = None
            cursor_pa: SelectionState | None = None
            for record in message.records:
                if record.kind == "EV":
                    cursor_ev = self._upsert_event(record.fields)
                    cursor_ma = None
                    cursor_pa = None
                elif record.kind == "MA":
                    cursor_ma = self._upsert_market(record.fields, cursor_ev)
                    cursor_pa = None
                elif record.kind == "PA":
                    cursor_pa = self._upsert_selection(record.fields, cursor_ma, cursor_ev)
                elif record.kind == "CL":
                    class_id = field_int(record.fields, "ID")
                    name = record.fields.get("NA")
                    if class_id is not None and name:
                        self.sport_classes[class_id] = name
            return

        if message.op == "U":
            self._apply_update(message.path, message.records)
            return

        if message.op == "D":
            self._apply_delete(message.path)

    @staticmethod
    def _path_candidates(path: str | None) -> tuple[str, ...]:
        """Possible state keys represented by a ZAP delta path."""
        if not path:
            return ()
        candidates = [path]
        if path.startswith("OV"):
            candidates.append(path[2:])
        if path.startswith("P") and "-" in path:
            candidates.append(path[1:])
        return tuple(dict.fromkeys(candidates))

    def _apply_delete(self, path: str | None) -> None:
        """Apply a ZAP delete and cascade cached children."""
        candidates = self._path_candidates(path)
        if not candidates:
            return

        for key in candidates:
            if key in self.selections:
                self.selections.pop(key, None)
                return

        for key in candidates:
            market = self.markets.pop(key, None)
            if market is None:
                continue
            drop_selections = [
                it
                for it, selection in self.selections.items()
                if (
                    selection.fi == market.fi
                    and selection.ma_id == market.market_id
                )
            ]
            for it in drop_selections:
                self.selections.pop(it, None)
            return

        for key in candidates:
            event = next(
                (item for item in self.events.values() if item.it == key),
                None,
            )
            if event is not None:
                self._drop_event(event.fi)
                return

    def _upsert_event(self, fields: dict[str, str]) -> EventState | None:
        fi = field_int(fields, "FI")
        if fi is None:
            return None
        event = self.events.get(fi)
        if event is None:
            event = EventState(fi=fi)
            self.events[fi] = event
        merge_fields(event.fields, fields)
        if fields.get("NA"):
            event.name = fields["NA"]
            event.team1, event.team2 = parse_match_teams(fields["NA"])
        if fields.get("CT"):
            event.competition = fields["CT"]
        sport_class = sport_class_from_event_fields(fields)
        if sport_class is not None:
            event.sport_class = sport_class
        if fields.get("SS"):
            event.score = fields["SS"]
        if fields.get("TM") is not None:
            event.minute = field_int(fields, "TM")
        if fields.get("TS") is not None:
            event.timer_secs = field_int(fields, "TS")
        if fields.get("TT") is not None:
            event.timer_ticking = fields.get("TT") == "1"
        if fields.get("TU"):
            event.timer_tu = fields["TU"]
        if fields.get("ML") is not None:
            event.match_length = field_int(fields, "ML")
        if fields.get("FS") is not None:
            event.live = fields.get("FS") == "1"
        if fields.get("IT"):
            event.it = fields["IT"]
        return event

    def _upsert_market(
        self,
        fields: dict[str, str],
        event: EventState | None,
    ) -> MarketState | None:
        it = fields.get("IT")
        if not it:
            fi = field_int(fields, "FI")
            mid = field_int(fields, "ID")
            if fi is not None and mid is not None:
                it = f"_ma_{fi}_{mid}"
            else:
                return None
        market = self.markets.get(it)
        if market is None:
            market = MarketState(it=it)
            self.markets[it] = market
        merge_fields(market.fields, fields)
        market.fi = field_int(fields, "FI") or market.fi
        market.market_id = field_int(fields, "ID") or market.market_id
        if fields.get("NA"):
            market.name = fields["NA"]
        if event is not None and market.fi is None:
            market.fi = event.fi
        return market

    def _upsert_selection(
        self,
        fields: dict[str, str],
        market: MarketState | None,
        event: EventState | None,
    ) -> SelectionState | None:
        it = fields.get("IT")
        if not it:
            return None
        selection = self.selections.get(it)
        if selection is None:
            selection = SelectionState(it=it)
            self.selections[it] = selection
        merge_fields(selection.fields, fields)
        selection.fi = field_int(fields, "FI") or selection.fi
        if market is not None:
            selection.ma_id = market.market_id or selection.ma_id
            if selection.fi is None:
                selection.fi = market.fi
        if event is not None and selection.fi is None:
            selection.fi = event.fi
        if fields.get("NA"):
            selection.name = fields["NA"]
        if fields.get("OR"):
            selection.order = field_int(fields, "OR")
        if fields.get("MA"):
            selection.ma_id = field_int(fields, "MA") or selection.ma_id
        if fields.get("OD"):
            selection.odds_frac = fields["OD"]
            selection.odds_decimal = fractional_to_decimal(fields["OD"])
        if fields.get("SU") is not None:
            selection.suspended = fields["SU"] == "1"
        return selection

    def _apply_update(self, path: str | None, records: list) -> None:
        patch: dict[str, str] = {}
        for record in records:
            patch.update(record.fields)

        if not patch:
            return

        selection = self._selection_for_path(path)
        event = self._event_for_path(path, selection)

        if selection is not None:
            merge_fields(selection.fields, patch)
            if patch.get("OD"):
                selection.odds_frac = patch["OD"]
                selection.odds_decimal = fractional_to_decimal(patch["OD"])
            if patch.get("SU") is not None:
                selection.suspended = patch["SU"] == "1"
            if patch.get("NA"):
                selection.name = patch["NA"]
            if patch.get("OR"):
                selection.order = field_int(patch, "OR")

        if event is not None:
            merge_fields(event.fields, patch)
            if patch.get("SS"):
                event.score = patch["SS"]
            if patch.get("TM") is not None:
                event.minute = field_int(patch, "TM")
            if patch.get("TS") is not None:
                event.timer_secs = field_int(patch, "TS")
            if patch.get("TT") is not None:
                event.timer_ticking = patch.get("TT") == "1"
            if patch.get("TU"):
                event.timer_tu = patch["TU"]
                event.fields["TU"] = patch["TU"]
            if patch.get("ML") is not None:
                event.match_length = field_int(patch, "ML")
            if patch.get("FS") is not None:
                event.live = patch.get("FS") == "1"

    def _selection_for_path(self, path: str | None) -> SelectionState | None:
        if not path:
            return None
        if path in self.selections:
            return self.selections[path]
        if path.startswith("OV"):
            return self.selections.get(path[2:])
        if path.startswith("P") and "-" in path:
            return self.selections.get(path[1:])
        return None

    def _event_for_path(
        self,
        path: str | None,
        selection: SelectionState | None,
    ) -> EventState | None:
        if selection is not None and selection.fi is not None:
            event = self.resolve_event_for_market_fi(selection.fi)
            if event is not None:
                return event
        if not path:
            return None
        for event in self.events.values():
            if event.it and path.startswith(event.it):
                return event
        return None

    def resolve_event_for_market_fi(self, market_fi: int) -> EventState | None:
        for event in self.events.values():
            if self.market_fi(event) == market_fi:
                return event
        return self.events.get(market_fi)

    def sport_class_for(self, event: EventState) -> int | None:
        if event.sport_class is not None:
            return event.sport_class
        return sport_class_from_event_fields(event.fields)

    def sport_name(self, event: EventState) -> str:
        sport_class = self.sport_class_for(event)
        if sport_class is not None:
            return self.sport_classes.get(sport_class) or f"Sport {sport_class}"
        return "Unknown"

    def export_events(self, *, live_only: bool = False) -> list[EventState]:
        """Events to export — all sports with odds when import_all, else soccer 1X2 only."""
        if import_all_from_socket():
            return self._export_all_events(live_only=live_only)
        events = self.soccer_events_with_main_market()
        if live_only:
            events = [e for e in events if e.live]
        return [e for e in events if not self._is_finished(e)]

    def drop_finished_events(self) -> int:
        """Remove finished / left-live matches from in-memory state."""
        drop_ids = [
            fi
            for fi, event in self.events.items()
            if self._is_match_event(event) and self._is_finished(event)
        ]
        for fi in drop_ids:
            self._drop_event(fi)
        return len(drop_ids)

    def _drop_event(self, fi: int) -> None:
        event = self.events.pop(fi, None)
        if event is None:
            return
        market_fi = self.market_fi(event)
        drop_markets = [
            it
            for it, market in self.markets.items()
            if market.fi in (fi, market_fi)
        ]
        for it in drop_markets:
            self.markets.pop(it, None)
        drop_sels = [
            it
            for it, sel in self.selections.items()
            if sel.fi in (fi, market_fi)
        ]
        for it in drop_sels:
            self.selections.pop(it, None)

    def _is_finished(self, event: EventState) -> bool:
        """
        True when a match has left the in-play book.

        Finished games often linger in ZAP state; do not persist them as live.
        Fully suspended markets are not treated as finished (betting blocked).
        """
        if not self._is_match_event(event):
            return False
        if not event.live:
            score = (event.score or "").strip()
            if score and score not in {"0-0", "0-0,0-0"}:
                return True
            return bool(event.minute is not None and event.minute > 0)

        # Still FS=1 but regulation clock stopped at/after match length (e.g. soccer 90:00).
        # Bet365 often keeps these open briefly after full time — drop from live UI.
        if self._is_past_regulation(event):
            return True

        # Still FS=1: finished only when priced selections were removed entirely.
        if self._event_has_odds(event):
            return False
        market_fi = self.market_fi(event)
        still_has_priced_rows = any(
            s.fi == market_fi and s.odds_decimal is not None
            for s in self.selections.values()
        )
        if still_has_priced_rows:
            return False
        return bool(event.score or event.minute is not None)

    def _is_past_regulation(self, event: EventState) -> bool:
        """
        Past regulation with a frozen clock.

        Real soccer: do NOT finish while prices remain (injury/VAR at 90+).
        Esoccer: short games (6/8/12 min) linger at ML with last OD — drop them.
        """
        if event.minute is None:
            return False
        if event.timer_ticking is True:
            return False
        ml = event.match_length
        if ml is None and self._is_esoccer(event):
            ml = self._infer_esoccer_match_length(event)
        if ml is None and event.sport_class == soccer_class_id():
            ml = 90
        if ml is None or event.minute < ml:
            return False
        # Virtual esoccer ends when the short clock hits ML (no injury time).
        if self._is_esoccer(event):
            return True
        # Still priced → keep live (FT linger with odds, or stoppage pause).
        if self._event_has_odds(event):
            return False
        market_fi = self.market_fi(event)
        if any(
            s.fi == market_fi and s.odds_decimal is not None
            for s in self.selections.values()
        ):
            return False
        return True

    @staticmethod
    def _infer_esoccer_match_length(event: EventState) -> int | None:
        """Parse 'Joc de 8 minute' / '8 minute' from competition when ML missing."""
        comp = event.competition or ""
        match = re.search(r"(\d+)\s*minute", comp, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _export_all_events(self, *, live_only: bool) -> list[EventState]:
        result: list[EventState] = []
        for event in self.events.values():
            if live_only and not event.live:
                continue
            if skip_esoccer() and self._is_esoccer(event):
                continue
            if not self._is_match_event(event):
                continue
            if self._is_finished(event):
                continue
            if not self._event_has_odds(event):
                continue
            result.append(event)
        result.sort(
            key=lambda e: (
                e.sport_class or 0,
                e.competition or "",
                e.name or "",
            )
        )
        return result

    def _resolve_ma_id(self, sel: SelectionState, market_fi: int) -> int | None:
        """Market id for a PA row — including orphans missing MA linkage."""
        if sel.ma_id is not None:
            return sel.ma_id
        market_ids = {
            m.market_id
            for m in self.markets.values()
            if m.fi == market_fi and m.market_id is not None
        }
        if len(market_ids) == 1:
            return next(iter(market_ids))
        # Delta feeds often update PA without an MA parent; OR 0/1/2 ⇒ primary.
        if sel.order is not None and sel.order in (0, 1, 2):
            return main_market_id()
        return None

    def markets_with_odds(
        self, event: EventState
    ) -> list[tuple[int, str | None, list[SelectionState]]]:
        """All markets on an event that have at least one priced selection.

        Includes suspended rows that still carry a last OD (Bet365 UI keeps
        showing those prices). Orphan PA rows without ma_id are attributed via
        `_resolve_ma_id` so esoccer mid-match deltas still export 1/X/2.
        """
        market_fi = self.market_fi(event)
        by_market: dict[int, list[SelectionState]] = {}
        for sel in self.selections.values():
            if sel.fi != market_fi or sel.odds_decimal is None:
                continue
            ma_id = self._resolve_ma_id(sel, market_fi)
            if ma_id is None:
                continue
            if sel.ma_id is None:
                sel.ma_id = ma_id
            by_market.setdefault(ma_id, []).append(sel)

        result: list[tuple[int, str | None, list[SelectionState]]] = []
        for ma_id, sels in by_market.items():
            name = self._market_name(market_fi, ma_id)
            sels.sort(key=lambda s: (s.order if s.order is not None else 99, s.it))
            result.append((ma_id, name, sels))
        result.sort(key=lambda item: (item[0], item[1] or ""))
        return result

    def _market_name(self, market_fi: int, market_id: int) -> str | None:
        for market in self.markets.values():
            if market.fi == market_fi and market.market_id == market_id:
                return market.name
        return None

    def _is_match_event(self, event: EventState) -> bool:
        name = event.name or ""
        it = str(event.fields.get("IT") or "")
        if it.startswith("P-") or it.startswith("PV_"):
            return False
        if not name.strip():
            return False
        lower = name.lower()
        return " v " in lower or " vs " in lower or " @ " in lower

    def _event_has_odds(self, event: EventState) -> bool:
        """True when we can export at least one priced market (incl. suspended)."""
        market_fi = self.market_fi(event)
        return any(
            s.fi == market_fi
            and s.odds_decimal is not None
            and self._resolve_ma_id(s, market_fi) is not None
            for s in self.selections.values()
        )

    def soccer_events_with_main_market(self) -> list[EventState]:
        market_id = main_market_id()
        soccer_id = soccer_class_id()
        result: list[EventState] = []
        for event in self.events.values():
            if event.sport_class != soccer_id:
                continue
            if skip_esoccer() and self._is_esoccer(event):
                continue
            if not self._has_main_market(event, market_id):
                continue
            result.append(event)
        result.sort(key=lambda e: (e.competition or "", e.name or ""))
        return result

    def market_fi(self, event: EventState) -> int:
        """Fixture id used on MA/PA rows (often OI, not EV.FI)."""
        oi = field_int(event.fields, "OI")
        return oi if oi is not None else event.fi

    def main_market_outcomes(self, event: EventState) -> list[SelectionState]:
        market_id = main_market_id()
        market_fi = self.market_fi(event)
        by_order: dict[int, SelectionState] = {}
        for s in self.selections.values():
            if s.fi != market_fi or s.odds_decimal is None or s.order is None:
                continue
            if self._resolve_ma_id(s, market_fi) != market_id:
                continue
            by_order[s.order] = s
        return [by_order[k] for k in sorted(by_order)]

    def _has_main_market(self, event: EventState, market_id: int) -> bool:
        market_fi = self.market_fi(event)
        return any(
            s.fi == market_fi
            and s.odds_decimal is not None
            and self._resolve_ma_id(s, market_fi) == market_id
            for s in self.selections.values()
        )

    @staticmethod
    def _is_esoccer(event: EventState) -> bool:
        comp = (event.competition or "").lower()
        if "esoccer" in comp or "e-soccer" in comp:
            return True
        ck = str(event.fields.get("CK") or "").upper()
        cc = str(event.fields.get("CC") or "").upper()
        return ck.startswith("ESOC") or cc.startswith("ESOC")
