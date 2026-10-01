"""Offline tests for the V3.3 Sleeper roster configuration parser."""

import ast
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("sleeper_v3_2.py")


def load_configuration_functions():
    """Compile pure configuration helpers without importing V3.2."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    function_names = {
        "parse_roster_configuration",
        "get_slot_eligible_positions",
        "expand_roster_slots",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    found = {function.name for function in functions}
    if found != function_names:
        raise RuntimeError(f"Missing configuration helpers: {function_names - found}")

    isolated_module = ast.Module(body=functions, type_ignores=[])
    namespace = {}
    exec(compile(isolated_module, str(SOURCE), "exec"), namespace)
    return namespace


CONFIGURATION = load_configuration_functions()
parse_roster_configuration = CONFIGURATION["parse_roster_configuration"]
get_slot_eligible_positions = CONFIGURATION["get_slot_eligible_positions"]
expand_roster_slots = CONFIGURATION["expand_roster_slots"]


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


class RosterSlotHelperTests(unittest.TestCase):
    def config(self, slots):
        return parse_roster_configuration(slots)

    def expanded(self, slots):
        return expand_roster_slots(self.config(slots))

    def test_nlfl_expands_to_expected_slot_instances(self):
        slots = self.expanded([
            "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
            "BN", "BN", "BN", "BN", "BN", "BN",
        ])
        self.assertEqual(
            [(slot["slot_code"], slot["ordinal"]) for slot in slots],
            [
                ("QB", 1), ("RB", 1), ("RB", 2),
                ("WR", 1), ("WR", 2), ("TE", 1),
                ("FLEX", 1), ("K", 1), ("DEF", 1),
                ("BN", 1), ("BN", 2), ("BN", 3),
                ("BN", 4), ("BN", 5), ("BN", 6),
            ],
        )
        self.assertEqual(slots[0]["eligible_positions"], ["QB"])
        self.assertTrue(slots[0]["is_direct"])
        self.assertTrue(slots[6]["is_flex"])
        self.assertEqual(slots[6]["eligible_positions"], ["RB", "WR", "TE"])

    def test_multiple_flex_slots_expand_with_one_based_ordinals(self):
        slots = self.expanded(["FLEX", "FLEX"])
        self.assertEqual(
            [(slot["slot_code"], slot["ordinal"]) for slot in slots],
            [("FLEX", 1), ("FLEX", 2)],
        )

    def test_mixed_flex_types_expand_deterministically(self):
        slots = self.expanded(["WRRB_FLEX", "REC_FLEX"])
        self.assertEqual([slot["slot_code"] for slot in slots], [
            "REC_FLEX", "WRRB_FLEX",
        ])
        by_code = {slot["slot_code"]: slot for slot in slots}
        self.assertEqual(by_code["WRRB_FLEX"]["eligible_positions"], ["RB", "WR"])
        self.assertEqual(by_code["REC_FLEX"]["eligible_positions"], ["WR", "TE"])

    def test_super_flex_uses_parser_eligibility(self):
        slot, = self.expanded(["SUPER_FLEX"])
        self.assertEqual(slot["eligible_positions"], ["QB", "RB", "WR", "TE"])
        self.assertTrue(slot["supported_by_analyzer"])

    def test_idp_flex_is_recognized_but_not_analyzer_supported(self):
        slot, = self.expanded(["IDP_FLEX"])
        self.assertTrue(slot["recognized"])
        self.assertFalse(slot["supported_by_analyzer"])
        self.assertEqual(slot["eligible_positions"], ["DL", "LB", "DB"])

    def test_zero_direct_slots_produce_only_configured_flex(self):
        slots = self.expanded(["FLEX"])
        self.assertFalse(any(slot["is_direct"] for slot in slots))
        self.assertEqual([slot["slot_code"] for slot in slots], ["FLEX"])

    def test_extra_direct_slots_expand_to_distinct_instances(self):
        slots = self.expanded(["RB", "RB", "RB"])
        self.assertEqual([slot["ordinal"] for slot in slots], [1, 2, 3])
        self.assertTrue(all(slot["eligible_positions"] == ["RB"] for slot in slots))

    def test_unknown_slots_are_preserved_and_remain_unsupported(self):
        slots = self.expanded(["CUSTOM_SLOT", "CUSTOM_SLOT"])
        self.assertEqual(len(slots), 2)
        self.assertTrue(all(slot["slot_type"] == "unknown" for slot in slots))
        self.assertTrue(all(not slot["recognized"] for slot in slots))
        self.assertTrue(all(not slot["supported_by_analyzer"] for slot in slots))
        self.assertTrue(all(slot["eligible_positions"] == [] for slot in slots))

    def test_empty_and_none_configuration_expand_to_no_slots(self):
        empty_configuration = parse_roster_configuration(None)
        self.assertEqual(expand_roster_slots(empty_configuration), [])
        self.assertEqual(expand_roster_slots(None), [])

    def test_slot_order_is_deterministic_independent_of_raw_order(self):
        first = self.expanded(["DEF", "FLEX", "WR", "QB", "K", "RB"])
        second = self.expanded(["RB", "K", "QB", "WR", "FLEX", "DEF"])
        self.assertEqual(first, second)

    def test_direct_slot_eligibility_lookup(self):
        config = self.config(["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"])
        for code in ("QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"):
            with self.subTest(code=code):
                self.assertEqual(get_slot_eligible_positions(code, config), [code])

    def test_each_flex_eligibility_lookup_uses_normalized_configuration(self):
        expected = {
            "FLEX": ["RB", "WR", "TE"],
            "WRRB_FLEX": ["RB", "WR"],
            "REC_FLEX": ["WR", "TE"],
            "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
            "IDP_FLEX": ["DL", "LB", "DB"],
        }
        config = self.config(list(expected))
        for code, positions in expected.items():
            with self.subTest(code=code):
                self.assertEqual(
                    get_slot_eligible_positions(code, config), positions
                )

    def test_recognized_and_analyzer_supported_are_distinct(self):
        slots = self.expanded(["K", "DEF", "DL", "IDP_FLEX", "CUSTOM_SLOT", "BN"])
        by_code = {slot["slot_code"]: slot for slot in slots}
        self.assertTrue(by_code["K"]["recognized"])
        self.assertTrue(by_code["K"]["supported_by_analyzer"])
        self.assertTrue(by_code["DEF"]["supported_by_analyzer"])
        self.assertTrue(by_code["DL"]["recognized"])
        self.assertFalse(by_code["DL"]["supported_by_analyzer"])
        self.assertTrue(by_code["IDP_FLEX"]["recognized"])
        self.assertFalse(by_code["IDP_FLEX"]["supported_by_analyzer"])
        self.assertFalse(by_code["CUSTOM_SLOT"]["recognized"])
        self.assertFalse(by_code["CUSTOM_SLOT"]["supported_by_analyzer"])
        self.assertEqual(by_code["BN"]["slot_type"], "nonstarter")
        self.assertFalse(by_code["BN"]["supported_by_analyzer"])

    def test_expanded_representation_is_json_serializable(self):
        slots = self.expanded(["QB", "FLEX", "IDP_FLEX", "BN", "CUSTOM_SLOT"])
        self.assertEqual(json.loads(json.dumps(slots)), slots)


if __name__ == "__main__":
    unittest.main()
