"""Catalog / site-name unit tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from adapters.base import ChangeType
from betcity_live.catalog import BetcityCatalog, CatalogEvent, parse_catalog_payload
from betcity_live.config import DEFAULT_SITE_NAME, BetcityConfig, normalize_site_name
from betcity_live.mapper import map_packet_to_changes
from betcity_live.poll import resolve_site_name


class NormalizeSiteNameTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(normalize_site_name("betcity."), DEFAULT_SITE_NAME)
        self.assertEqual(normalize_site_name("betcity"), DEFAULT_SITE_NAME)
        self.assertEqual(normalize_site_name("betcity.ru"), DEFAULT_SITE_NAME)

    def test_resolve_ignores_other_bookmakers(self) -> None:
        self.assertEqual(resolve_site_name(None, "bet365.com"), DEFAULT_SITE_NAME)
        self.assertEqual(resolve_site_name("betcity.", "bet365.com"), DEFAULT_SITE_NAME)
        self.assertEqual(resolve_site_name("betcity.ru", None), DEFAULT_SITE_NAME)


class CatalogParseTests(unittest.TestCase):
    def test_parse_names(self) -> None:
        payload = {
            "ok": True,
            "reply": {
                "sports": {
                    "1": {
                        "id_sp": 1,
                        "name_sp": "Football",
                        "chmps": {
                            "10": {
                                "id_ch": 10,
                                "name_ch": "Premier League",
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "name_ht": "Home FC",
                                        "name_at": "Away FC",
                                        "date_ev": 1783700000,
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }
        events = parse_catalog_payload(payload)
        self.assertIn(99, events)
        ev = events[99]
        self.assertEqual(ev.team1, "Home FC")
        self.assertEqual(ev.team2, "Away FC")
        self.assertEqual(ev.league_name, "Premier League")
        self.assertEqual(ev.sport_name, "Football")


class MapperCatalogTests(unittest.TestCase):
    def test_fixture_uses_catalog_names(self) -> None:
        packet = {
            "type": 1,
            "md": 1,
            "reply": {
                "sports": {
                    "1": {
                        "id_sp": 1,
                        "chmps": {
                            "10": {
                                "id_ch": 10,
                                "evts": {"99": {"id_ev": 99}},
                            }
                        },
                    }
                }
            },
        }
        catalog = MagicMock(spec=BetcityCatalog)
        catalog.get.return_value = CatalogEvent(
            event_id=99,
            sport_id=1,
            sport_name="Football",
            championship_id=10,
            league_name="Premier League",
            team1="Home FC",
            team2="Away FC",
            start_time_unix=1783700000,
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        fixture = next(c for c in changes if c.change_type == ChangeType.FIXTURE)
        self.assertEqual(fixture.payload["team1"], "Home FC")
        self.assertEqual(fixture.payload["team2"], "Away FC")
        self.assertEqual(fixture.payload["league_name"], "Premier League")
        self.assertEqual(fixture.payload["sport_name"], "Football")


if __name__ == "__main__":
    unittest.main()
