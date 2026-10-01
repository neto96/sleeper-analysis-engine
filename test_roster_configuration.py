"""Offline tests for the V3.3 Sleeper roster configuration parser."""

import ast
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("sleeper_v3_2.py")


def load_parser():
    """Compile only the pure parser, avoiding V3.2 module side effects."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "parse_roster_configuration"
    )
    isolated_module = ast.Module(body=[function], type_ignores=[])
    namespace = {}
    exec(compile(isolated_module, str(SOURCE), "exec"), namespace)
    return namespace["parse_roster_configuration"]


parse_roster_configuration = load_parser()


class RosterConfigurationParserTests(unittest.TestCase):
    def test_main_parses_and_passes_league_roster_configuration(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        main = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        assignments = [
            node for node in ast.walk(main)
            if isinstance(node, ast.Assign)
        ]

        configuration_assignment = next(
            node for node in assignments
            if any(
                isinstance(target, ast.Name)
                and target.id == "roster_configuration"
                for target in node.targets
            )
        )
        parser_call = configuration_assignment.value
        self.assertIsInstance(parser_call, ast.Call)
        self.assertIsInstance(parser_call.func, ast.Name)
        self.assertEqual(parser_call.func.id, "parse_roster_configuration")
        league_field = parser_call.args[0]
        self.assertIsInstance(league_field, ast.Call)
        self.assertIsInstance(league_field.func, ast.Attribute)
        self.assertEqual(league_field.func.attr, "get")
        self.assertIsInstance(league_field.func.value, ast.Name)
        self.assertEqual(league_field.func.value.id, "league")
        self.assertEqual(ast.literal_eval(league_field.args[0]), "roster_positions")

        analysis_assignment = next(
            node for node in assignments
            if isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "snapshot"
            and isinstance(node.targets[0].slice, ast.Constant)
            and node.targets[0].slice.value == "fantasy_analysis"
        )
        analysis_call = analysis_assignment.value
        self.assertIsInstance(analysis_call, ast.Call)
        self.assertIsInstance(analysis_call.func, ast.Name)
        self.assertEqual(analysis_call.func.id, "build_fantasy_analysis")
        self.assertEqual(
            [argument.id for argument in analysis_call.args],
            ["roster_data", "roster_configuration"],
        )
    def test_standard_nlfl_configuration(self):
        parsed = parse_roster_configuration([
            "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
            "BN", "BN", "BN", "BN", "BN", "BN",
        ])
        self.assertEqual(parsed, {
            "direct_slots": {
                "DEF": 1, "K": 1, "QB": 1, "RB": 2, "TE": 1, "WR": 2,
            },
            "flex_slots": {
                "FLEX": {
                    "count": 1,
                    "eligible_positions": ["RB", "WR", "TE"],
                },
            },
            "nonstarter_slots": {"BN": 6},
            "unrecognized_slots": {},
        })

    def test_repeated_direct_slots_are_counted(self):
        parsed = parse_roster_configuration(["RB", "RB", "RB", "QB", "QB"])
        self.assertEqual(parsed["direct_slots"], {"QB": 2, "RB": 3})

    def test_bench_slots_do_not_become_starting_requirements(self):
        parsed = parse_roster_configuration(["BN", "BN", "WR"])
        self.assertEqual(parsed["direct_slots"], {"WR": 1})
        self.assertEqual(parsed["nonstarter_slots"], {"BN": 2})
        self.assertNotIn("BN", parsed["direct_slots"])
        self.assertNotIn("BN", parsed["flex_slots"])

    def test_each_supported_flex_code_has_explicit_eligibility(self):
        expected = {
            "FLEX": ["RB", "WR", "TE"],
            "WRRB_FLEX": ["RB", "WR"],
            "REC_FLEX": ["WR", "TE"],
            "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
            "IDP_FLEX": ["DL", "LB", "DB"],
        }
        for slot_code, eligible_positions in expected.items():
            with self.subTest(slot_code=slot_code):
                parsed = parse_roster_configuration([slot_code])
                self.assertEqual(parsed["flex_slots"][slot_code], {
                    "count": 1,
                    "eligible_positions": eligible_positions,
                })
                self.assertEqual(parsed["direct_slots"], {})

    def test_unknown_slot_codes_are_preserved_and_counted(self):
        parsed = parse_roster_configuration(["CUSTOM_SLOT", "CUSTOM_SLOT"])
        self.assertEqual(parsed["unrecognized_slots"], {"CUSTOM_SLOT": 2})

    def test_empty_and_missing_input(self):
        empty = {
            "direct_slots": {},
            "flex_slots": {},
            "nonstarter_slots": {},
            "unrecognized_slots": {},
        }
        self.assertEqual(parse_roster_configuration([]), empty)
        self.assertEqual(parse_roster_configuration(None), empty)

    def test_multiple_flex_slots_keep_count_and_single_shared_eligibility(self):
        parsed = parse_roster_configuration([
            "FLEX", "FLEX", "SUPER_FLEX", "SUPER_FLEX",
        ])
        self.assertEqual(parsed["flex_slots"], {
            "FLEX": {
                "count": 2,
                "eligible_positions": ["RB", "WR", "TE"],
            },
            "SUPER_FLEX": {
                "count": 2,
                "eligible_positions": ["QB", "RB", "WR", "TE"],
            },
        })

    def test_output_is_json_serializable(self):
        parsed = parse_roster_configuration([
            "QB", "FLEX", "IDP_FLEX", "BN", "CUSTOM_SLOT",
        ])
        encoded = json.dumps(parsed, sort_keys=True)
        self.assertIsInstance(encoded, str)
        self.assertEqual(json.loads(encoded), parsed)


if __name__ == "__main__":
    unittest.main()
