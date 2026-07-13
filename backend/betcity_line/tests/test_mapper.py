"""Mapper / state tests for Betcity prematch line."""

from __future__ import annotations

import unittest

from adapters.base import ChangeType
from betcity_line.mapper import map_packet_to_changes, map_state_to_changes
from betcity_line.state import BetcityLineState


SAMPLE_PACKET = {
    "reply": {
        "ntime": 1750000000,
        "sports": {
            "1": {
                "id_sp": 1,
                "name_sp": "Football",
                "chmps": {
                    "10": {
                        "id_ch": 10,
                        "name_ch": "Test League",
                        "evts": {
                            "1001": {
                                "id_ev": 1001,
                                "name_ht": "Home FC",
                                "name_at": "Away FC",
                                "date_ev": 1750100000,
                                "main": {
                                    "69": {
                                        "data": {
                                            "1001": {
                                                "blocks": {
                                                    "Wm": {
                                                        "P1": {"kf": 1.85, "st": 2},
                                                        "P2": {"kf": 2.05, "st": 2},
                                                        "X": {"kf": 3.4, "st": 2},
                                                        "st": 2,
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                            },
                            "1002": {
                                "id_ev": 1002,
                                "name_ht": "Outright Only",
                                "date_ev": 1750200000,
                                "main": {
                                    "69": {
                                        "data": {
                                            "1002": {
                                                "blocks": {
                                                    "YNm": {
                                                        "YN": {"kf": 1.5, "st": 2},
                                                        "st": 2,
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                            },
                        },
                    }
                },
            }
        },
    }
}


class BetcityLineMapperTests(unittest.TestCase):
    def test_wm_p1_p2_maps_to_921_923_place_line(self) -> None:
        changes = map_packet_to_changes(SAMPLE_PACKET, version=1750000000)
        fixtures = [c for c in changes if c.change_type == ChangeType.FIXTURE]
        self.assertEqual(len(fixtures), 2)
        for fix in fixtures:
            self.assertEqual(fix.payload.get("place"), "line")

        odds = [c for c in changes if c.change_type == ChangeType.ODDS]
        self.assertEqual(len(odds), 1)
        self.assertEqual(odds[0].match_payload_id, 1001)
        outcomes = odds[0].payload["outcomes"]
        self.assertEqual([o["factor_id"] for o in outcomes], [921, 922, 923])
        self.assertEqual(outcomes[0]["odds"], 1.85)
        self.assertEqual(outcomes[1]["odds"], 3.4)
        self.assertEqual(outcomes[2]["odds"], 2.05)

    def test_delta_deletes_event(self) -> None:
        state = BetcityLineState()
        state.apply_packet(SAMPLE_PACKET, replace=True)
        self.assertIn(1001, state.events)

        delta = {
            "reply": {
                "ntime": 1750000001,
                "sports": {
                    "1": {
                        "id_sp": 1,
                        "chmps": {
                            "10": {
                                "id_ch": 10,
                                "evts": {
                                    "1001": {"id_ev": 1001, "del_ev": 1},
                                },
                            }
                        },
                    }
                },
            }
        }
        state.apply_packet(delta, replace=False)
        self.assertNotIn(1001, state.events)
        self.assertIn(1002, state.events)

        changes = map_state_to_changes(state, version=1750000001)
        ids = {c.match_payload_id for c in changes if c.change_type == ChangeType.FIXTURE}
        self.assertEqual(ids, {1002})

    def test_betting_locked_when_st_1(self) -> None:
        packet = {
            "reply": {
                "ntime": 1,
                "sports": {
                    "1": {
                        "id_sp": 1,
                        "name_sp": "Football",
                        "chmps": {
                            "10": {
                                "id_ch": 10,
                                "name_ch": "L",
                                "evts": {
                                    "9": {
                                        "id_ev": 9,
                                        "name_ht": "A",
                                        "name_at": "B",
                                        "main": {
                                            "69": {
                                                "data": {
                                                    "9": {
                                                        "blocks": {
                                                            "Wm": {
                                                                "P1": {"kf": 1.5, "st": 1},
                                                                "P2": {"kf": 2.5, "st": 1},
                                                                "st": 1,
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
            }
        }
        changes = map_packet_to_changes(packet, version=1)
        status = [
            c for c in changes if c.change_type == ChangeType.BETTING_STATUS
        ]
        self.assertEqual(status[0].payload["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
