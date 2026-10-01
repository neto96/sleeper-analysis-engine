"""Offline characterization tests for V3.2 fantasy analysis."""

import ast
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
        analysis = ANALYSIS["build_fantasy_analysis"](roster)
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
        analysis = ANALYSIS["build_fantasy_analysis"](roster)
        team = analysis["teams"]["3"]
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


if __name__ == "__main__":
    unittest.main()
