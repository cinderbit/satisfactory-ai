"""Unit tests for blueprint_planner: fit-check + auto-split. No game required."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_planner import PlanResult, TokenRow
from blueprint_planner import (
    DESIGNER_BUILD_AREA_M, fit_report, rows_from_plan, split_for_tier,
    spawner_recipe_token, spawner_machine_token, format_command,
)


def screws_plan() -> PlanResult:
    return PlanResult(
        token_rows=[
            TokenRow("Constructor", "Screws", 3, 120, 120, 0, "Recipe_Screw_C"),
            TokenRow("Constructor", "Iron Rod", 2, 30, 30, 0, "Recipe_IronRod_C"),
            TokenRow("Smelter", "Iron Ingot", 1, 30, 30, 0, "Recipe_IngotIron_C"),
        ],
        bom={"Desc_OreIron_C": 30.0},
        byproducts={},
    )


class TokenTests(unittest.TestCase):
    def test_recipe_token_strips_wrapper(self):
        self.assertEqual(spawner_recipe_token("Recipe_IngotIron_C"), "IngotIron")
        self.assertEqual(spawner_recipe_token("Recipe_IronRod_C"), "IronRod")
        self.assertEqual(spawner_recipe_token("Recipe_Screw_C"), "Screw")

    def test_recipe_token_fallback_to_display(self):
        self.assertEqual(spawner_recipe_token("", "Iron Rod"), "IronRod")

    def test_oilrefinery_machine_token(self):
        self.assertEqual(spawner_machine_token("OilRefinery"), "Refinery")
        self.assertEqual(spawner_machine_token("Constructor"), "Constructor")

    def test_single_command_format(self):
        cmd = format_command(rows_from_plan(screws_plan()))
        self.assertEqual(
            cmd,
            "/FactorySpawner 3 Constructor Screw, 2 Constructor IronRod, 1 Smelter IngotIron",
        )


class FitTests(unittest.TestCase):
    def test_screws_strip_is_24x53(self):
        rep = fit_report(rows_from_plan(screws_plan()))
        self.assertEqual(round(rep["width_m"]), 24)
        self.assertEqual(round(rep["depth_m"]), 53)

    def test_screws_fit_no_single_designer(self):
        rep = fit_report(rows_from_plan(screws_plan()))
        self.assertFalse(any(rep["tiers"].values()))
        self.assertIsNone(rep["smallest_single_tier"])


class SplitTests(unittest.TestCase):
    def test_every_blueprint_fits_the_tier(self):
        rows = rows_from_plan(screws_plan())
        for tier, size in DESIGNER_BUILD_AREA_M.items():
            bps, warnings = split_for_tier(rows, tier)
            self.assertTrue(bps)
            self.assertFalse(warnings)
            for bp in bps:
                self.assertLessEqual(bp.width_m, size, f"width over Mk{tier}")
                self.assertLessEqual(bp.depth_m, size, f"depth over Mk{tier}")

    def test_split_preserves_all_machines(self):
        rows = rows_from_plan(screws_plan())
        bps, _ = split_for_tier(rows, 3)
        # total machine count by (machine, recipe) is conserved across blueprints
        def counts(rs):
            d = {}
            for r in rs:
                d[(r.machine_type, r.recipe_class)] = d.get((r.machine_type, r.recipe_class), 0) + r.count
            return d
        merged = {}
        for bp in bps:
            for k, v in counts(bp.rows).items():
                merged[k] = merged.get(k, 0) + v
        self.assertEqual(merged, counts(rows))

    def test_wide_row_is_split_by_count(self):
        # 12 Constructors @ 8m = 96m wide -> must split to fit Mk1 (32m -> 4/row)
        plan = PlanResult(
            token_rows=[TokenRow("Constructor", "Screws", 12, 480, 480, 0, "Recipe_Screw_C")],
            bom={}, byproducts={},
        )
        bps, warnings = split_for_tier(rows_from_plan(plan), 1)
        self.assertFalse(warnings)
        for bp in bps:
            self.assertLessEqual(bp.width_m, 32)
        total = sum(r.count for bp in bps for r in bp.rows)
        self.assertEqual(total, 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
