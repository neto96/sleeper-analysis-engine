"""Offline characterization tests for V3.2 fantasy analysis."""

import ast
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("sleeper_v3_2.py")
FUNCTIONS = {
    "clean_name",
    "fantasy_value_tier",
    "fantasy_importance_score",
    "build_league_position_analysis",
    "classify_league_scarcity",
    "calculate_optimal_lineup",
    "build_fantasy_analysis",
    "parse_roster_configuration",
}


def _unused_analysis_stage(*_args, **_kwargs):
    """Keep this test focused on the analysis stages under characterization."""
    return {}


def load_analysis_functions():
    """Compile selected definitions without importing V3.2 or running main()."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
    ]
    found = {node.name for node in definitions}
    if found != FUNCTIONS:
        raise RuntimeError(f"Could not find expected functions: {FUNCTIONS - found}")

    namespace = {
        "classify_position_need": _unused_analysis_stage,
        "classify_starting_depth": _unused_analysis_stage,
        "calculate_lineup_strength": _unused_analysis_stage,
        "calculate_roster_surplus": _unused_analysis_stage,
        "calculate_roster_replacement_cost": _unused_analysis_stage,
        "calculate_player_protection": _unused_analysis_stage,
    }
    isolated_module = ast.Module(body=definitions, type_ignores=[])
    exec(compile(isolated_module, str(SOURCE), "exec"), namespace)
    return namespace


ANALYSIS = load_analysis_functions()
NLFL_ROSTER_CONFIGURATION = ANALYSIS["parse_roster_configuration"]([
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
    "BN", "BN", "BN", "BN", "BN", "BN",
])


class V32AnalysisCharacterizationTests(unittest.TestCase):
    def test_fantasy_value_tier_boundaries(self):
        cases = [
            (None, "unknown"),
            ("not-a-rank", "unknown"),
            (0, "elite"),
            (50, "elite"),
            (51, "strong"),
            (120, "strong"),
            (121, "useful"),
            (250, "useful"),
            (251, "fringe"),
            (400, "fringe"),
            (401, "deep_waiver"),
        ]
        for rank, expected in cases:
            with self.subTest(rank=rank):
                self.assertEqual(
                    ANALYSIS["fantasy_value_tier"]({"search_rank": rank}),
                    expected,
                )

    def test_meaningful_players_counts_rank_tiers_regardless_of_roster_state(self):
        players = [
            {"player_id": "1", "position": "RB", "search_rank": 50},
            {"player_id": "2", "position": "RB", "search_rank": 120},
            {"player_id": "3", "position": "RB", "search_rank": 250},
            {"player_id": "4", "position": "RB", "search_rank": 400},
            {"player_id": "5", "position": "RB", "search_rank": None},
            {"player_id": "6", "position": "RB", "search_rank": 1,
             "injury_status": "IR"},
        ]
        roster = {
            "3": {
                "team_name": "Test Team",
                "owner": "Test Owner",
                "players": players,
                "starters": [players[0]],
                "reserve": [players[1]],
                "taxi": [players[2]],
            }
        }
        analysis = ANALYSIS["build_fantasy_analysis"](roster, NLFL_ROSTER_CONFIGURATION)
        rb_summary = analysis["teams"]["3"]["position_summary"]["RB"]

        # Elite/strong/useful count; fringe and unknown do not. IR, reserve,
        # and taxi status do not exclude a player from this count.
        self.assertEqual(rb_summary["meaningful_players"], 4)

    def test_league_scarcity_thresholds(self):
        cases = [
            (8, 9, "high"),       # median depth cutoff
            (20, 1.5, "high"),    # meaningful-player cutoff
            (14, 3, "moderate"),  # median depth cutoff
            (20, 2.5, "moderate"),
            (15, 2.6, "low"),
        ]
        for median_depth, meaningful, expected in cases:
            with self.subTest(median_depth=median_depth, meaningful=meaningful):
                result = ANALYSIS["classify_league_scarcity"]({
                    "RB": {
                        "median_depth_score": median_depth,
                        "average_depth_score": median_depth,
                        "average_meaningful_players": meaningful,
                    }
                })
                self.assertEqual(result["RB"]["scarcity"], expected)

    def test_hard_coded_lineup_requirements_and_single_flex(self):
        roster = {
            "3": {
                "team_name": "Test Team",
                "owner": "Test Owner",
                "players": [
                    {"player_id": "qb", "position": "QB", "search_rank": 10},
                    {"player_id": "rb1", "position": "RB", "search_rank": 20},
                    {"player_id": "rb2", "position": "RB", "search_rank": 30},
                    {"player_id": "rb3", "position": "RB", "search_rank": 40},
                    {"player_id": "wr1", "position": "WR", "search_rank": 50},
                    {"player_id": "wr2", "position": "WR", "search_rank": 60},
                    {"player_id": "wr3", "position": "WR", "search_rank": 70},
                    {"player_id": "te1", "position": "TE", "search_rank": 80},
                    {"player_id": "k", "position": "K", "search_rank": 90},
                    {"player_id": "def", "position": "DEF", "search_rank": 100},
                ],
                "starters": [],
                "reserve": [],
                "taxi": [],
            }
        }
        analysis = ANALYSIS["build_fantasy_analysis"](roster, NLFL_ROSTER_CONFIGURATION)
        team = analysis["teams"]["3"]
        self.assertEqual(analysis["roster_configuration"], NLFL_ROSTER_CONFIGURATION)
        self.assertEqual(analysis["lineup_requirements"], {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1,
            "K": 1, "DEF": 1, "FLEX": 1,
        })
        self.assertEqual(analysis["flex_positions"], ["RB", "TE", "WR"])
        self.assertEqual(
            {position: len(players) for position, players
             in team["optimal_lineup"].items()},
            {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
        )
        self.assertEqual(
            {
                position: [player["player_id"] for player in players]
                for position, players in team["optimal_lineup"].items()
            },
            {
                "QB": ["qb"], "RB": ["rb1", "rb2"],
                "WR": ["wr1", "wr2"], "TE": ["te1"],
                # RB3 outranks WR3 under the existing tier + importance score.
                "FLEX": ["rb3"],
            },
        )
        self.assertEqual(team["lineup_coverage"]["K"]["required"], 1)
        self.assertEqual(team["lineup_coverage"]["DEF"]["required"], 1)
        self.assertEqual(team["lineup_coverage"]["FLEX"]["coverage"], 1)
        self.assertEqual(team["lineup_coverage"]["FLEX"]["shortage"], 0)
        json.dumps(analysis)


class ConfigurationAwareOptimalLineupTests(unittest.TestCase):
    def configuration(self, slots):
        return ANALYSIS["parse_roster_configuration"](slots)

    def player(self, player_id, position, tier="elite", importance=0):
        return {
            "player_id": player_id,
            "position": position,
            "fantasy_value_tier": tier,
            "importance_score": importance,
        }

    def optimize(self, slots, players):
        positions = {position: [] for position in ("QB", "RB", "WR", "TE")}
        for player in players:
            positions[player["position"]].append(player)
        return ANALYSIS["calculate_optimal_lineup"](
            positions, self.configuration(slots)
        )

    def test_one_flex_selects_best_remaining_eligible_player(self):
        lineup = self.optimize(["RB", "FLEX"], [
            self.player("rb1", "RB", importance=30),
            self.player("rb2", "RB", "strong", 15),
            self.player("wr1", "WR", "useful", 45),
            self.player("te1", "TE", "strong", 25),
        ])
        self.assertEqual(lineup["RB"][0]["player_id"], "rb1")
        self.assertEqual(lineup["FLEX"][0]["player_id"], "te1")

    def test_flex_global_optimum_avoids_greedy_slot_order_trap(self):
        lineup = self.optimize(["FLEX", "REC_FLEX"], [
            self.player("wr1", "WR", importance=1),
            self.player("rb1", "RB", "strong", 50),
            self.player("te1", "TE", "useful", 80),
        ])
        self.assertEqual(lineup["FLEX"][0]["player_id"], "rb1")
        self.assertEqual(lineup["REC_FLEX"][0]["player_id"], "wr1")

    def test_super_flex_can_use_qb_without_double_counting_and_is_optimal(self):
        lineup = self.optimize(["QB", "SUPER_FLEX"], [
            self.player("qb1", "QB", importance=30),
            self.player("qb2", "QB", importance=20),
            self.player("rb1", "RB", "strong", 50),
            self.player("wr1", "WR", "useful", 80),
            self.player("te1", "TE", "fringe", 99),
        ])
        selected = [
            player["player_id"]
            for players in lineup.values()
            for player in players
        ]
        self.assertEqual(lineup["QB"][0]["player_id"], "qb1")
        self.assertEqual(lineup["SUPER_FLEX"][0]["player_id"], "qb2")
        self.assertEqual(selected.count("qb2"), 1)
        self.assertEqual(len(selected), len(set(selected)))

    def test_multiple_flex_slots_use_unique_best_eligible_players(self):
        lineup = self.optimize(["FLEX", "FLEX"], [
            self.player("rb1", "RB", importance=10),
            self.player("wr1", "WR", importance=20),
            self.player("te1", "TE", importance=30),
        ])
        selected = lineup["FLEX"]
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({p["player_id"] for p in selected}), 2)
        self.assertEqual(
            {p["player_id"] for p in selected}, {"wr1", "te1"}
        )

    def test_mixed_flex_types_respect_each_eligibility_set(self):
        lineup = self.optimize(["WRRB_FLEX", "REC_FLEX"], [
            self.player("qb1", "QB", importance=100),
            self.player("rb1", "RB", importance=20),
            self.player("wr1", "WR", importance=30),
            self.player("te1", "TE", importance=40),
        ])
        self.assertEqual(lineup["WRRB_FLEX"][0]["player_id"], "wr1")
        self.assertEqual(lineup["REC_FLEX"][0]["player_id"], "te1")
        self.assertNotIn("qb1", {
            p["player_id"] for players in lineup.values() for p in players
        })

    def test_direct_slot_counts_can_increase_or_be_zero(self):
        players = [
            self.player("rb1", "RB", importance=30),
            self.player("rb2", "RB", importance=20),
            self.player("rb3", "RB", importance=10),
            self.player("wr1", "WR", importance=30),
            self.player("wr2", "WR", importance=20),
            self.player("wr3", "WR", importance=10),
        ]
        with self.subTest(configuration="extra RB"):
            lineup = self.optimize(["RB", "RB", "RB"], players)
            self.assertEqual([p["player_id"] for p in lineup["RB"]],
                             ["rb1", "rb2", "rb3"])
        with self.subTest(configuration="zero RB"):
            lineup = self.optimize(["WR"], players)
            self.assertEqual(lineup["RB"], [])
        with self.subTest(configuration="extra WR"):
            lineup = self.optimize(["WR", "WR", "WR"], players)
            self.assertEqual([p["player_id"] for p in lineup["WR"]],
                             ["wr1", "wr2", "wr3"])

    def test_insufficient_players_leave_configured_slots_empty(self):
        lineup = self.optimize(["RB", "RB", "FLEX"], [
            self.player("rb1", "RB")
        ])
        self.assertEqual(len(lineup["RB"]), 1)
        self.assertEqual(len(lineup["FLEX"]), 0)

    def test_cross_position_duplicate_player_id_is_selected_once(self):
        duplicate_rb = self.player("shared", "RB", importance=50)
        duplicate_wr = self.player("shared", "WR", importance=50)
        lineup = ANALYSIS["calculate_optimal_lineup"](
            {"QB": [], "RB": [duplicate_rb], "WR": [duplicate_wr], "TE": []},
            self.configuration(["RB", "FLEX"]),
        )
        selected_ids = [
            player["player_id"]
            for players in lineup.values()
            for player in players
        ]
        self.assertEqual(selected_ids.count("shared"), 1)

    def test_position_group_is_authoritative_as_in_v32_data_model(self):
        player = self.player("rb1", "WR", importance=50)
        lineup = ANALYSIS["calculate_optimal_lineup"](
            {"QB": [], "RB": [player], "WR": [], "TE": []},
            self.configuration(["RB"]),
        )
        self.assertEqual(lineup["RB"][0]["position"], "RB")

    def test_k_and_def_remain_outside_optimizer_selection(self):
        lineup = ANALYSIS["calculate_optimal_lineup"](
            {
                "QB": [], "RB": [], "WR": [], "TE": [],
                "K": [self.player("k", "K", importance=999)],
                "DEF": [self.player("def", "DEF", importance=999)],
            },
            NLFL_ROSTER_CONFIGURATION,
        )
        self.assertNotIn("K", lineup)
        self.assertNotIn("DEF", lineup)

    def test_output_has_no_duplicate_ids_and_is_json_serializable(self):
        lineup = self.optimize(["RB", "FLEX", "FLEX"], [
            self.player("rb1", "RB"), self.player("wr1", "WR"),
            self.player("te1", "TE"),
        ])
        selected_ids = [
            player["player_id"]
            for players in lineup.values()
            for player in players
        ]
        self.assertEqual(len(selected_ids), len(set(selected_ids)))
        json.dumps(lineup)


if __name__ == "__main__":
    unittest.main()
