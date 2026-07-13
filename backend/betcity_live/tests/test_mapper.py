"""Mapper tests using captured Betcity WebSocket frames."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from adapters.base import ChangeType
from betcity_live.catalog import CatalogEvent
from betcity_live.mapper import map_packet_to_changes, map_state_to_changes, state_summary
from betcity_live.state import BetcityFeedState

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
RICH = Path(__file__).resolve().parents[1] / "samples_rich"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeCatalog:
    def __init__(self, events: dict[int, CatalogEvent]) -> None:
        self._events = events

    def get(self, event_id: int) -> CatalogEvent | None:
        return self._events.get(event_id)


def _catalog_for_state(state: BetcityFeedState) -> _FakeCatalog:
    events = {
        event_id: CatalogEvent(
            event_id=event_id,
            sport_id=event.sport_id,
            sport_name="Football",
            championship_id=event.championship_id,
            league_name=f"LeagueName {event.championship_id or 0}",
            team1=f"Home {event_id}",
            team2=f"Away {event_id}",
        )
        for event_id, event in state.events.items()
    }
    return _FakeCatalog(events)


class BetcityMapperTests(unittest.TestCase):
    def test_apply_sports_and_main_frames(self) -> None:
        state = BetcityFeedState()
        # Prefer richer captures when present; fall back to Phase A samples.
        frames: list[Path] = []
        if RICH.is_dir():
            frames = sorted(RICH.glob("frame_*.json"))[:8]
        if not frames and SAMPLES.is_dir():
            frames = sorted(SAMPLES.glob("frame_*.txt"))[:2]
        self.assertTrue(frames, "expected sample frames under samples/ or samples_rich/")

        for path in frames:
            state.apply_frame(_load(path))

        self.assertGreater(len(state.events), 0)
        catalog = _catalog_for_state(state)
        changes = map_state_to_changes(state, version=1, catalog=catalog)
        types = {c.change_type for c in changes}
        self.assertIn(ChangeType.FIXTURE, types)

        odds = [c for c in changes if c.change_type == ChangeType.ODDS]
        if odds:
            outcomes = odds[0].payload.get("outcomes") or []
            self.assertLessEqual(len(outcomes), 3)
            factor_ids = [o["factor_id"] for o in outcomes]
            self.assertTrue(set(factor_ids).issubset({921, 922, 923}))

        summary = state_summary(state)
        self.assertGreaterEqual(summary.fixtures, 1)

    def test_main_wm_p1_p2_maps_to_921_923(self) -> None:
        packet = {
            "type": 2,
            "md": 100,
            "reply": {
                "sports": {
                    "1": {
                        "id_sp": 1,
                        "chmps": {
                            "10": {
                                "id_ch": 10,
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "sc_ev_cmx": {"main": [["1", "0"]]},
                                        "status_ev": 1,
                                    }
                                },
                            }
                        },
                    }
                },
                "main": {
                    "99": {
                        "69": {
                            "name": "Result",
                            "data": {
                                "99": {
                                    "blocks": {
                                        "Wm": {
                                            "P1": {"kf": 1.9, "st": 2},
                                            "P2": {"kf": 2.1, "st": 2},
                                            "st": 2,
                                        }
                                    }
                                }
                            },
                        }
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                )
            }
        )
        changes = map_packet_to_changes(packet, version=100, catalog=catalog)
        odds = [c for c in changes if c.change_type == ChangeType.ODDS]
        self.assertEqual(len(odds), 1)
        outcomes = odds[0].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in outcomes], [921, 923])
        self.assertEqual(outcomes[0]["odds"], 1.9)
        self.assertEqual(outcomes[1]["odds"], 2.1)

        score = next(c for c in changes if c.change_type == ChangeType.SCORE)
        self.assertEqual(score.payload["score1"], 1)
        self.assertEqual(score.payload["score2"], 0)

    def test_catalog_scores_fill_missing_ws_scores(self) -> None:
        """HTTP on-air catalog supplies scores when WS sports deltas omit them."""
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 1,
                                    }
                                },
                            }
                        },
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                    score1=3,
                    score2=1,
                    raw_scores={"main": [["3", "1"]]},
                    minute=49,
                )
            }
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        score = next(c for c in changes if c.change_type == ChangeType.SCORE)
        self.assertEqual(score.payload["score1"], 3)
        self.assertEqual(score.payload["score2"], 1)
        self.assertEqual(score.payload["timer_display"], "49:00")
        self.assertEqual(score.payload["score_function"], "run")

    def test_timer_is_run_maps_to_score_function(self) -> None:
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 1,
                                        "m_tmr": {
                                            "tmr": 2705,
                                            "is_run": 0,
                                            "format": "mm:ss",
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                    score1=1,
                    score2=0,
                )
            }
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        score = next(c for c in changes if c.change_type == ChangeType.SCORE)
        self.assertEqual(score.payload["timer_display"], "45:05")
        self.assertEqual(score.payload["timer_seconds"], 2705)
        self.assertEqual(score.payload["score_function"], "stop")

    def test_catalog_scores_override_stale_ws_scores(self) -> None:
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 1,
                                        "sc_ev_cmx": {"main": [["0", "0"]]},
                                    }
                                },
                            }
                        },
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                    score1=1,
                    score2=2,
                )
            }
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        score = next(c for c in changes if c.change_type == ChangeType.SCORE)
        self.assertEqual(score.payload["score1"], 1)
        self.assertEqual(score.payload["score2"], 2)

    def test_blocked_events_map_to_blocked_state(self) -> None:
        """Main market outcome st=1 means locked, not catalog status_ev."""
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 0,
                                        "sc_ev_cmx": {"main": [["0", "0"]]},
                                    }
                                },
                            }
                        },
                    }
                },
                "main": {
                    "99": {
                        "69": {
                            "data": {
                                "99": {
                                    "blocks": {
                                        "Wm": {
                                            "st": 1,
                                            "P1": {"kf": 3.4, "st": 1},
                                            "P2": {"kf": 1.9, "st": 1},
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                    status_ev=0,
                )
            }
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        status = next(c for c in changes if c.change_type == ChangeType.BETTING_STATUS)
        self.assertEqual(status.payload["state"], "blocked")

    def test_open_market_st2_is_unblocked_even_if_status_ev_zero(self) -> None:
        """status_ev=0 is common for live events and must not force Blocked."""
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 0,
                                    }
                                },
                            }
                        },
                    }
                },
                "main": {
                    "99": {
                        "69": {
                            "data": {
                                "99": {
                                    "blocks": {
                                        "Wm": {
                                            "st": 2,
                                            "P1": {"kf": 2.1, "st": 2},
                                            "P2": {"kf": 1.7, "st": 2},
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            },
        }
        catalog = _FakeCatalog(
            {
                99: CatalogEvent(
                    event_id=99,
                    sport_id=1,
                    sport_name="Football",
                    championship_id=10,
                    league_name="Test League",
                    team1="Home",
                    team2="Away",
                    status_ev=0,
                )
            }
        )
        changes = map_packet_to_changes(packet, version=1, catalog=catalog)
        status = next(c for c in changes if c.change_type == ChangeType.BETTING_STATUS)
        self.assertEqual(status.payload["state"], "unblocked")

    def test_unnamed_events_are_not_mapped(self) -> None:
        """Without catalog names, do not persist Event/League placeholders."""
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
                                "evts": {
                                    "99": {
                                        "id_ev": 99,
                                        "status_ev": 1,
                                        "sc_ev_cmx": {"main": [["0", "0"]]},
                                    }
                                },
                            }
                        },
                    }
                },
            },
        }
        changes = map_packet_to_changes(packet, version=1)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
