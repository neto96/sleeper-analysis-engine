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
    "classify_position_need",
    "classify_starting_depth",
    "get_position_slot_requirements",
    "calculate_lineup_strength",
    "calculate_optimal_lineup",
    "build_fantasy_analysis",
    "parse_roster_configuration",
    "get_slot_eligible_positions",
    "expand_roster_slots",
    "assign_roster_slot_coverage",
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
        coverage_summary = team["lineup_coverage"]["summary"]
        self.assertEqual(coverage_summary["supported_configured_slots"], 9)
        self.assertEqual(coverage_summary["covered_slots"], 9)
        self.assertEqual(coverage_summary["uncovered_slots"], 0)
        self.assertEqual(
            len({item["player_id"] for item in coverage_summary["assignments"]}),
            9,
        )
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


class ConfigurationAwareLineupStrengthTests(unittest.TestCase):
    positions = ("QB", "RB", "WR", "TE")

    def make_team(self, roster_slots, players, direct_shortages=None):
        configuration = ANALYSIS["parse_roster_configuration"](roster_slots)
        position_groups = {position: [] for position in self.positions}
        for player in players:
            position_groups[player["position"]].append(player)

        slots = ANALYSIS["expand_roster_slots"](configuration)
        direct_requirements = {
            position: sum(
                slot["slot_type"] == "direct"
                and slot["slot_code"] == position
                for slot in slots
            )
            for position in self.positions
        }
        meaningful_tiers = {"elite", "strong", "useful"}
        starting_depth = {
            position: {
                "required": direct_requirements[position],
                "direct_shortage": (direct_shortages or {}).get(position, 0),
                "meaningful_players": sum(
                    player.get("fantasy_value_tier") in meaningful_tiers
                    for player in position_groups[position]
                ),
            }
            for position in self.positions
        }
        team = {
            "positions": position_groups,
            "starting_depth": starting_depth,
            "optimal_lineup": ANALYSIS["calculate_optimal_lineup"](
                position_groups, configuration
            ),
        }
        return configuration, team

    @staticmethod
    def player(player_id, position, tier="useful", importance=0):
        return {
            "player_id": player_id,
            "position": position,
            "fantasy_value_tier": tier,
            "importance_score": importance,
        }

    def evaluate(self, roster_slots, players, direct_shortages=None):
        configuration, team = self.make_team(
            roster_slots, players, direct_shortages
        )
        return ANALYSIS["calculate_lineup_strength"](team, configuration), team

    def standard_players(self):
        return [
            self.player("qb", "QB", "elite"),
            self.player("rb1", "RB", "elite"),
            self.player("rb2", "RB", "strong"),
            self.player("rb3", "RB", "useful"),
            self.player("wr1", "WR", "elite"),
            self.player("wr2", "WR", "strong"),
            self.player("te", "TE", "strong"),
        ]

    def test_nlfl_strength_regression(self):
        strength, _ = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            self.standard_players(),
        )
        self.assertEqual(
            {position: value["rating"] for position, value in strength.items()},
            {"QB": "adequate", "RB": "adequate", "WR": "weak", "TE": "adequate"},
        )
        self.assertEqual(strength["RB"]["flex_used"], 1)

    def test_no_flex_uses_only_configured_direct_assignments(self):
        strength, _ = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE"],
            self.standard_players(),
        )
        self.assertTrue(all(value["flex_used"] == 0 for value in strength.values()))
        self.assertEqual(strength["RB"]["rating"], "adequate")
        self.assertEqual(strength["WR"]["rating"], "weak")

    def test_two_flex_slots_participate_independently(self):
        players = self.standard_players() + [
            self.player("wr3", "WR", "useful"),
            self.player("te2", "TE", "strong"),
        ]
        strength, team = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"],
            players,
        )
        self.assertEqual(
            sum(value["flex_used"] for value in strength.values()), 2
        )
        self.assertEqual(len(team["optimal_lineup"]["FLEX"]), 2)

    def test_wrrb_flex_excludes_te(self):
        strength, team = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX"],
            self.standard_players() + [self.player("te2", "TE", "elite")],
        )
        self.assertEqual(strength["TE"]["flex_used"], 0)
        assigned = team["optimal_lineup"]["WRRB_FLEX"]
        self.assertEqual(len(assigned), 1)
        self.assertIn(assigned[0]["position"], {"RB", "WR"})

    def test_rec_flex_excludes_rb(self):
        strength, team = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE", "REC_FLEX"],
            self.standard_players() + [
                self.player("rb4", "RB", "elite"),
                self.player("te2", "TE", "elite"),
            ],
        )
        self.assertEqual(strength["RB"]["flex_used"], 0)
        assigned = team["optimal_lineup"]["REC_FLEX"]
        self.assertEqual(len(assigned), 1)
        self.assertIn(assigned[0]["position"], {"WR", "TE"})

    def test_super_flex_allows_qb_and_uses_player_once(self):
        strength, team = self.evaluate(
            ["QB", "RB", "RB", "WR", "WR", "TE", "SUPER_FLEX"],
            self.standard_players() + [self.player("qb2", "QB", "elite", 10)],
        )
        assigned = team["optimal_lineup"]["SUPER_FLEX"]
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]["position"], "QB")
        lineup_ids = [
            player["player_id"]
            for players in team["optimal_lineup"].values()
            for player in players
        ]
        self.assertEqual(len(lineup_ids), len(set(lineup_ids)))
        self.assertEqual(strength["QB"]["flex_used"], 1)

    def test_unique_player_assignment_prevents_direct_flex_double_count(self):
        players = [
            self.player("wr-strong", "WR", "elite"),
            self.player("wr-weaker", "WR", "fringe"),
            self.player("rb", "RB", "useful"),
        ]
        strength, team = self.evaluate(["WR", "FLEX"], players)
        lineup_ids = [
            player["player_id"]
            for players in team["optimal_lineup"].values()
            for player in players
        ]
        self.assertEqual(len(lineup_ids), len(set(lineup_ids)))
        self.assertEqual(strength["WR"]["flex_used"], 0)
        self.assertEqual(strength["RB"]["flex_used"], 1)

    def test_insufficient_players_keep_empty_slot_weak_behavior(self):
        strength, team = self.evaluate(
            ["QB", "QB"],
            [self.player("qb", "QB", "elite")],
            direct_shortages={"QB": 1},
        )
        self.assertEqual(len(team["optimal_lineup"]["QB"]), 1)
        self.assertEqual(strength["QB"]["rating"], "weak")

    def test_multiple_overlapping_flex_assignments_are_deterministic(self):
        roster_slots = ["RB", "WR", "FLEX", "REC_FLEX"]
        players = [
            self.player("rb1", "RB", "elite"),
            self.player("rb2", "RB", "useful"),
            self.player("wr1", "WR", "elite"),
            self.player("wr2", "WR", "strong"),
            self.player("te1", "TE", "strong"),
        ]
        strength, team = self.evaluate(roster_slots, players)
        _, repeated_team = self.make_team(roster_slots, players)
        lineup_ids = [
            player["player_id"]
            for assigned in team["optimal_lineup"].values()
            for player in assigned
        ]
        self.assertEqual(len(lineup_ids), len(set(lineup_ids)))
        self.assertEqual(
            sum(value["flex_used"] for value in strength.values()), 2
        )
        self.assertEqual(team["optimal_lineup"], repeated_team["optimal_lineup"])

    def test_existing_rb_strength_thresholds_are_unchanged(self):
        slots = ["RB"]
        strong_players = [
            self.player("rb1", "RB", "elite"),
            self.player("rb2", "RB", "strong"),
            self.player("rb3", "RB", "useful"),
        ]
        strength, _ = self.evaluate(slots, strong_players)
        self.assertEqual(strength["RB"]["rating"], "strong")

        adequate, _ = self.evaluate(slots, strong_players[:2])
        self.assertEqual(adequate["RB"]["rating"], "adequate")


class ConfigurationAwareLineupCoverageTests(unittest.TestCase):
    def player(self, player_id, position, search_rank=20, **extra):
        return {
            "player_id": player_id,
            "position": position,
            "search_rank": search_rank,
            **extra,
        }

    def analyze(self, roster_slots, players, **roster_overrides):
        roster = {
            "team_name": "Coverage Test",
            "owner": "Test Owner",
            "players": players,
            "starters": [],
            "reserve": [],
            "taxi": [],
            **roster_overrides,
        }
        return ANALYSIS["build_fantasy_analysis"](
            {"3": roster},
            ANALYSIS["parse_roster_configuration"](roster_slots),
        )

    def test_nlfl_configuration_reports_unique_slot_coverage(self):
        players = [
            self.player("qb", "QB"),
            self.player("rb1", "RB"), self.player("rb2", "RB"),
            self.player("rb3", "RB"),
            self.player("wr1", "WR"), self.player("wr2", "WR"),
            self.player("wr3", "WR"),
            self.player("te1", "TE"),
            self.player("k", "K"), self.player("def", "DEF"),
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            players,
        )
        team = analysis["teams"]["3"]
        self.assertEqual(analysis["lineup_requirements"], {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1,
            "K": 1, "DEF": 1, "FLEX": 1,
        })
        self.assertEqual(team["lineup_coverage"]["summary"]["covered_slots"], 9)
        self.assertEqual(team["lineup_coverage"]["K"]["direct_coverage"], 1)
        self.assertEqual(team["lineup_coverage"]["DEF"]["direct_coverage"], 1)

    def test_two_generic_flex_slots_do_not_double_count_direct_players(self):
        players = [
            self.player("qb", "QB"),
            self.player("rb1", "RB"), self.player("rb2", "RB"),
            self.player("rb3", "RB"),
            self.player("wr1", "WR"), self.player("wr2", "WR"),
            self.player("wr3", "WR"),
            self.player("te1", "TE"), self.player("te2", "TE"),
            self.player("k", "K"), self.player("def", "DEF"),
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"],
            players,
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        assignments = coverage["summary"]["assignments"]
        self.assertEqual(coverage["FLEX"]["coverage"], 2)
        self.assertEqual(len(assignments), 10)
        self.assertEqual(
            len({assignment["player_id"] for assignment in assignments}),
            len(assignments),
        )

    def test_mixed_flex_types_share_players_without_reuse(self):
        analysis = self.analyze(
            ["WRRB_FLEX", "REC_FLEX"],
            [
                self.player("wr1", "WR"), self.player("wr2", "WR"),
                self.player("rb1", "RB"), self.player("te1", "TE"),
            ],
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        self.assertEqual(coverage["flex_slots"]["WRRB_FLEX"]["coverage"], 1)
        self.assertEqual(coverage["flex_slots"]["REC_FLEX"]["coverage"], 1)
        ids = [item["player_id"] for item in coverage["summary"]["assignments"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_super_flex_accepts_qb_rb_or_wr_with_unique_assignment(self):
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "SUPER_FLEX"],
            [
                self.player("qb1", "QB"), self.player("qb2", "QB"),
                self.player("rb1", "RB"), self.player("rb2", "RB"),
                self.player("rb3", "RB"),
                self.player("wr1", "WR"), self.player("wr2", "WR"),
                self.player("wr3", "WR"),
            ],
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        super_flex = [
            item for item in coverage["summary"]["assignments"]
            if item["slot_code"] == "SUPER_FLEX"
        ]
        self.assertEqual(len(super_flex), 1)
        self.assertIn(super_flex[0]["position"], {"QB", "RB", "WR"})
        ids = [item["player_id"] for item in coverage["summary"]["assignments"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_k_and_def_coverage_is_separate_from_offensive_flex(self):
        analysis = self.analyze(
            ["K", "DEF", "FLEX"],
            [self.player("k", "K"), self.player("def", "DEF"),
             self.player("wr", "WR")],
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        self.assertEqual(coverage["K"]["direct_coverage"], 1)
        self.assertEqual(coverage["DEF"]["direct_coverage"], 1)
        self.assertEqual(coverage["FLEX"]["coverage"], 1)
        flex_assignment = next(
            item for item in coverage["summary"]["assignments"]
            if item["slot_type"] == "flex"
        )
        self.assertEqual(flex_assignment["player_id"], "wr")

    def test_zero_flex_does_not_invent_flex_demand(self):
        analysis = self.analyze(["RB"], [self.player("rb", "RB")])
        self.assertEqual(analysis["lineup_requirements"]["FLEX"], 0)
        self.assertEqual(analysis["flex_positions"], [])
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        self.assertEqual(coverage["FLEX"]["required"], 0)
        self.assertEqual(coverage["FLEX"]["coverage"], 0)

    def test_zero_direct_position_requirement_stays_zero(self):
        analysis = self.analyze(
            ["WR"], [self.player("rb", "RB"), self.player("wr", "WR")]
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        self.assertEqual(analysis["lineup_requirements"]["RB"], 0)
        self.assertEqual(coverage["RB"]["required"], 0)
        self.assertEqual(coverage["RB"]["direct_coverage"], 0)

    def test_overlapping_flex_slots_cannot_cover_more_slots_than_players(self):
        analysis = self.analyze(
            ["FLEX", "REC_FLEX"],
            [self.player("only-wr", "WR")],
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        assignments = coverage["summary"]["assignments"]
        unique_candidate_ids = {"only-wr"}
        self.assertEqual(coverage["FLEX"]["required"], 2)
        self.assertEqual(coverage["FLEX"]["coverage"], 1)
        self.assertLessEqual(coverage["summary"]["covered_slots"], len(unique_candidate_ids))
        self.assertEqual(
            len({item["player_id"] for item in assignments}), len(assignments)
        )

    def test_unknown_and_idp_slots_are_visible_but_not_supported_coverage(self):
        analysis = self.analyze(
            ["RB", "CUSTOM_SLOT", "IDP_FLEX"],
            [self.player("rb", "RB")],
        )
        self.assertEqual(
            analysis["roster_configuration"]["unrecognized_slots"],
            {"CUSTOM_SLOT": 1},
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        self.assertEqual(coverage["summary"]["unsupported_slots"], {
            "CUSTOM_SLOT": 1, "IDP_FLEX": 1,
        })
        self.assertEqual(coverage["FLEX"]["supported_required"], 0)
        self.assertEqual(coverage["FLEX"]["unsupported"], 1)

    def test_coverage_preserves_direct_and_flex_availability_rules(self):
        players = [
            self.player("ir", "RB", injury_status="IR"),
            self.player("inactive", "RB", status="Inactive"),
            self.player("reserve", "RB"),
        ]
        analysis = self.analyze(
            ["RB", "FLEX"],
            players,
            reserve=[{"player_id": "reserve"}],
        )
        coverage = analysis["teams"]["3"]["lineup_coverage"]
        assignments = coverage["summary"]["assignments"]
        direct = next(item for item in assignments if item["slot_type"] == "direct")
        flex = next(item for item in assignments if item["slot_type"] == "flex")
        self.assertEqual(direct["player_id"], "ir")
        self.assertEqual(flex["player_id"], "reserve")
        self.assertEqual(coverage["FLEX"]["eligible_players"], 1)

    def test_nlfl_position_need_and_starting_depth_regression(self):
        players = [
            self.player("qb1", "QB", 10), self.player("qb2", "QB", 100),
            self.player("rb1", "RB", 10), self.player("rb2", "RB", 20),
            self.player("rb3", "RB", 60), self.player("rb4", "RB", 180),
            self.player("wr1", "WR", 10), self.player("wr2", "WR", 60),
            self.player("wr3", "WR", 180),
            self.player("te1", "TE", 10),
        ]
        starters = [
            {"player_id": player_id}
            for player_id in ("qb1", "rb1", "rb2", "wr1", "wr2", "te1")
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            players,
            starters=starters,
        )
        team = analysis["teams"]["3"]
        for position in ("QB", "RB", "WR", "TE"):
            with self.subTest(position=position):
                self.assertEqual(team["position_need"][position]["need"], "moderate")
        self.assertEqual(team["starting_depth"]["QB"]["starting_depth"], "deep")
        self.assertEqual(team["starting_depth"]["RB"]["starting_depth"], "deep")
        self.assertEqual(team["starting_depth"]["WR"]["starting_depth"], "adequate")
        self.assertEqual(team["starting_depth"]["TE"]["starting_depth"], "thin")
        self.assertEqual(team["starting_depth"]["RB"]["flex_available"], 1)

    def test_no_flex_keeps_direct_requirements_only(self):
        players = [
            self.player("qb", "QB"),
            self.player("rb1", "RB"), self.player("rb2", "RB"),
            self.player("wr1", "WR"), self.player("wr2", "WR"),
            self.player("te", "TE"),
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "TE"],
            players,
            starters=[{"player_id": p["player_id"]} for p in players],
        )
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["required"], 2)
        self.assertEqual(team["starting_depth"]["RB"]["flex_available"], 0)
        self.assertEqual(team["starting_depth"]["WR"]["flex_available"], 0)
        self.assertEqual(team["position_need"]["RB"]["need"], "moderate")

    def test_two_flex_slots_remain_shared_across_positions(self):
        players = [
            self.player("qb", "QB"),
            self.player("rb1", "RB"), self.player("rb2", "RB"),
            self.player("rb3", "RB"),
            self.player("wr1", "WR"), self.player("wr2", "WR"),
            self.player("wr3", "WR"),
            self.player("te1", "TE"), self.player("te2", "TE"),
        ]
        starters = [
            {"player_id": player_id}
            for player_id in ("qb", "rb1", "rb2", "wr1", "wr2", "te1")
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"],
            players,
            starters=starters,
        )
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["required"], 2)
        self.assertEqual(team["starting_depth"]["WR"]["required"], 2)
        self.assertEqual(team["starting_depth"]["TE"]["required"], 1)
        self.assertEqual(analysis["lineup_requirements"]["FLEX"], 2)
        flex_depth_total = sum(
            team["starting_depth"][position]["flex_available"]
            for position in ("QB", "RB", "WR", "TE")
        )
        self.assertLessEqual(flex_depth_total, 2)

    def test_wrrb_flex_does_not_create_te_flex_supply(self):
        analysis = self.analyze(
            ["WRRB_FLEX"],
            [self.player("rb", "RB"), self.player("wr", "WR"),
             self.player("te", "TE")],
        )
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["flex_available"], 1)
        self.assertEqual(team["starting_depth"]["WR"]["flex_available"], 0)
        self.assertEqual(team["starting_depth"]["TE"]["flex_available"], 0)
        self.assertEqual(team["starting_depth"]["TE"]["required"], 0)

    def test_rec_flex_does_not_create_rb_flex_supply(self):
        analysis = self.analyze(
            ["REC_FLEX"],
            [self.player("rb", "RB"), self.player("wr", "WR"),
             self.player("te", "TE")],
        )
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["flex_available"], 0)
        self.assertEqual(team["starting_depth"]["WR"]["flex_available"], 1)
        self.assertEqual(team["starting_depth"]["TE"]["flex_available"], 0)

    def test_super_flex_can_contribute_to_qb_rb_wr_or_te_depth(self):
        players = [
            self.player("qb1", "QB"), self.player("qb2", "QB"),
            self.player("rb1", "RB"), self.player("rb2", "RB"),
            self.player("rb3", "RB"),
            self.player("wr1", "WR"), self.player("wr2", "WR"),
            self.player("wr3", "WR"), self.player("te", "TE"),
        ]
        analysis = self.analyze(
            ["QB", "RB", "RB", "WR", "WR", "SUPER_FLEX"],
            players,
            starters=[
                {"player_id": p}
                for p in ("qb1", "rb1", "rb2", "wr1", "wr2")
            ],
        )
        team = analysis["teams"]["3"]
        assigned_position = team["optimal_lineup"]["SUPER_FLEX"][0]["position"]
        self.assertIn(assigned_position, {"QB", "RB", "WR", "TE"})
        self.assertEqual(
            team["starting_depth"][assigned_position]["flex_available"],
            1,
        )

    def test_zero_direct_and_flex_demand_does_not_mark_position_short(self):
        analysis = self.analyze(["WR"], [self.player("wr", "WR")])
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["required"], 0)
        self.assertEqual(team["starting_depth"]["RB"]["starting_depth"], "adequate")
        self.assertNotEqual(team["position_need"]["RB"]["need"], "high")

    def test_overlapping_player_is_not_counted_for_direct_and_flex_depth(self):
        analysis = self.analyze(
            ["RB", "FLEX"],
            [self.player("rb1", "RB")],
            starters=[{"player_id": "rb1"}],
        )
        team = analysis["teams"]["3"]
        depth = team["starting_depth"]["RB"]
        self.assertEqual(depth["required"], 1)
        self.assertEqual(depth["meaningful_players"], 1)
        self.assertEqual(depth["flex_available"], 0)
        self.assertEqual(team["lineup_coverage"]["summary"]["covered_slots"], 1)

    def test_extra_direct_depth_uses_existing_thresholds_scaled_to_slots(self):
        players = [
            self.player("rb1", "RB", 10), self.player("rb2", "RB", 20),
            self.player("rb3", "RB", 60), self.player("rb4", "RB", 180),
        ]
        analysis = self.analyze(
            ["RB", "RB", "RB"],
            players,
            starters=[{"player_id": p} for p in ("rb1", "rb2", "rb3")],
        )
        depth = analysis["teams"]["3"]["starting_depth"]["RB"]
        self.assertEqual(depth["required"], 3)
        self.assertEqual(depth["starting_depth"], "adequate")

    def test_unknown_slots_do_not_create_supported_position_demand(self):
        analysis = self.analyze(
            ["CUSTOM_SLOT"], [self.player("rb", "RB")]
        )
        team = analysis["teams"]["3"]
        self.assertEqual(team["starting_depth"]["RB"]["required"], 0)
        self.assertEqual(team["starting_depth"]["RB"]["starting_depth"], "adequate")
        self.assertEqual(
            team["lineup_coverage"]["summary"]["unsupported_slots"],
            {"CUSTOM_SLOT": 1},
        )


class ConfigurationAwareLeaguePositionAnalysisTests(unittest.TestCase):
    def roster_team(self, roster_id, roster_slots, players):
        roster = {
            "team_name": f"Team {roster_id}",
            "owner": "Test Owner",
            "players": players,
            "starters": [],
            "reserve": [],
            "taxi": [],
        }
        configuration = ANALYSIS["parse_roster_configuration"](roster_slots)
        result = ANALYSIS["build_fantasy_analysis"](
            {str(roster_id): roster}, configuration
        )
        team = result["teams"][str(roster_id)]
        team["roster_configuration"] = configuration
        return configuration, team

    def analyze_league(self, roster_specs):
        teams = {}
        fallback_configuration = None
        for roster_id, roster_slots, players in roster_specs:
            configuration, team = self.roster_team(
                roster_id, roster_slots, players
            )
            fallback_configuration = fallback_configuration or configuration
            teams[str(roster_id)] = team
        return ANALYSIS["build_league_position_analysis"]({
            "roster_configuration": fallback_configuration,
            "teams": teams,
        })

    @staticmethod
    def player(player_id, position, search_rank=20):
        return {
            "player_id": player_id,
            "position": position,
            "search_rank": search_rank,
        }

    def test_nlfl_direct_and_flex_demand_regression(self):
        league = self.analyze_league([(
            1,
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            [self.player("qb", "QB"), self.player("rb1", "RB"),
             self.player("rb2", "RB"), self.player("wr1", "WR"),
             self.player("wr2", "WR"), self.player("te", "TE"),
             self.player("k", "K"), self.player("def", "DEF")],
        )])
        demand = league["configuration_demand"]
        self.assertEqual(demand["direct_demand_by_position"], {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1,
        })
        self.assertEqual(demand["flex_demand_by_slot_code"]["FLEX"]["count"], 1)
        self.assertEqual(demand["total_configured_starting_slots"], 9)
        self.assertEqual(
            league["RB"]["median_depth_score"],
            league["RB"]["teams"][0]["depth_score"],
        )
        self.assertEqual(league["RB"]["median_total"], 2)
        self.assertEqual(league["RB"]["average_meaningful_players"], 2)
        self.assertEqual(league["FLEX"]["configured_slots"], 1)

    def test_no_flex_does_not_invent_flex_demand(self):
        league = self.analyze_league([(
            1, ["QB", "RB", "RB", "WR", "WR", "TE"],
            [self.player("rb", "RB")],
        )])
        self.assertEqual(league["FLEX"]["configured_slots"], 0)
        self.assertEqual(league["FLEX"]["average_meaningful_players"], 0)
        self.assertEqual(
            league["configuration_demand"]["flex_demand_by_slot_code"], {}
        )
        self.assertEqual(league["configuration_demand"]["direct_demand_by_position"]["RB"], 2)

    def test_two_generic_flex_slots_are_shared_demand(self):
        league = self.analyze_league([(
            1, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"],
            [self.player("rb", "RB")],
        )])
        demand = league["configuration_demand"]
        self.assertEqual(demand["direct_demand_by_position"]["RB"], 2)
        self.assertEqual(demand["direct_demand_by_position"]["WR"], 2)
        self.assertEqual(demand["direct_demand_by_position"]["TE"], 1)
        self.assertEqual(demand["flex_demand_by_slot_code"]["FLEX"]["count"], 2)
        self.assertEqual(league["FLEX"]["configured_slots"], 2)
        self.assertEqual(league["RB"]["eligible_flex_slot_instances"], 2)
        self.assertEqual(league["WR"]["eligible_flex_slot_instances"], 2)
        self.assertEqual(league["TE"]["eligible_flex_slot_instances"], 2)

    def test_wrrb_and_rec_flex_eligibility_are_separate(self):
        league = self.analyze_league([
            (1, ["WRRB_FLEX"], [self.player("rb", "RB")]),
            (2, ["REC_FLEX"], [self.player("wr", "WR")]),
        ])
        demand = league["configuration_demand"]
        self.assertEqual(demand["flex_demand_by_slot_code"]["WRRB_FLEX"]["eligible_positions"], ["RB", "WR"])
        self.assertEqual(demand["flex_demand_by_slot_code"]["REC_FLEX"]["eligible_positions"], ["WR", "TE"])
        self.assertEqual(demand["eligible_flex_slot_instances_by_position"], {
            "QB": 0, "RB": 1, "WR": 2, "TE": 1, "K": 0, "DEF": 0,
        })

    def test_super_flex_is_one_shared_slot_for_offensive_positions(self):
        league = self.analyze_league([(
            1, ["SUPER_FLEX"], [self.player("qb", "QB")],
        )])
        demand = league["configuration_demand"]
        self.assertEqual(demand["total_configured_starting_slots"], 1)
        self.assertEqual(demand["flex_demand_by_slot_code"]["SUPER_FLEX"]["count"], 1)
        self.assertEqual(demand["direct_demand_by_position"], {
            "QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DEF": 0,
        })
        self.assertEqual(
            demand["eligible_flex_slot_instances_by_position"]["QB"], 1
        )

    def test_mixed_roster_configurations_sum_actual_roster_demand(self):
        league = self.analyze_league([
            (1, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"], []),
            (2, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"], []),
            (3, ["QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX"], []),
        ])
        demand = league["configuration_demand"]
        self.assertEqual(demand["direct_demand_by_position"]["QB"], 3)
        self.assertEqual(demand["direct_demand_by_position"]["RB"], 6)
        self.assertEqual(demand["flex_demand_by_slot_code"]["FLEX"]["count"], 3)
        self.assertEqual(demand["flex_demand_by_slot_code"]["WRRB_FLEX"]["count"], 1)
        self.assertEqual(demand["total_configured_starting_slots"], 22)

    def test_multiple_flex_types_count_actual_slots_not_eligible_position_sum(self):
        league = self.analyze_league([(
            1, ["FLEX", "REC_FLEX"], [],
        )])
        demand = league["configuration_demand"]
        self.assertEqual(demand["total_configured_starting_slots"], 2)
        self.assertEqual(league["FLEX"]["configured_slots"], 2)
        self.assertEqual(demand["eligible_flex_slot_instances_by_position"], {
            "QB": 0, "RB": 1, "WR": 2, "TE": 2, "K": 0, "DEF": 0,
        })

    def test_flex_supply_deduplicates_player_ids_across_groups(self):
        configuration, team = self.roster_team(
            1, ["FLEX", "REC_FLEX"],
            [self.player("shared", "RB"), self.player("shared", "WR")],
        )
        league = ANALYSIS["build_league_position_analysis"]({
            "roster_configuration": configuration,
            "teams": {"1": team},
        })
        self.assertEqual(
            league["FLEX"]["teams"][0]["meaningful_flex_players"], 1
        )

        configuration, team = self.roster_team(
            2, ["RB", "FLEX", "REC_FLEX"],
            [self.player("shared", "RB"), self.player("shared", "WR")],
        )
        league = ANALYSIS["build_league_position_analysis"]({
            "roster_configuration": configuration,
            "teams": {"2": team},
        })
        self.assertEqual(
            league["FLEX"]["teams"][0]["meaningful_flex_players"], 0
        )

    def test_unknown_and_unsupported_slots_do_not_become_position_demand(self):
        league = self.analyze_league([(
            1, ["CUSTOM_SLOT", "IDP_FLEX", "RB"],
            [self.player("rb", "RB")],
        )])
        demand = league["configuration_demand"]
        self.assertEqual(demand["direct_demand_by_position"]["RB"], 1)
        self.assertEqual(demand["direct_demand_by_position"]["QB"], 0)
        self.assertEqual(demand["flex_demand_by_slot_code"], {})
        self.assertEqual(demand["total_configured_starting_slots"], 3)
        self.assertEqual(demand["supported_starting_slots"], 1)
        self.assertEqual(demand["unsupported_slot_counts"], {
            "CUSTOM_SLOT": 1, "IDP_FLEX": 1,
        })


if __name__ == "__main__":
    unittest.main()
