"""
test_step4.py

End-to-end tests for the Step 4 advisor (pure Python, no game required).
Covers: recipe planner, fluid normalization, alternates, NL parsing,
FRM client over real HTTP (mock server), discovered-node filtering,
siting, and miner clock math.

Run:  python -m unittest tests.test_step4 -v
   or python tests/test_step4.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recipe_planner import load_recipes, plan
from miner_planner import plan_miners
from siting import find_site
from world_state import FRMClient, discovered_nodes, Purity
from advisor import parse_command

from tests.mock_frm import MockFRMServer

FIXTURES = Path(__file__).parent / "fixtures"
RECIPES = str(FIXTURES / "recipes_sample.json")


class RecipePlannerTests(unittest.TestCase):
    def setUp(self):
        self.recipes = load_recipes(RECIPES)

    def test_screws_chain_machine_counts(self):
        # 120 screws/min: standard chain
        #   Screw:     40/min/machine -> 3 Constructors
        #   Iron Rod:  15/min/machine, need 30/min -> 2 Constructors
        #   Iron Ingot:30/min/machine, need 30/min -> 1 Smelter
        result = plan("Desc_IronScrew_C", 120.0, self.recipes)
        counts = {(r.machine_type, r.recipe_name): r.count for r in result.token_rows}

        self.assertEqual(counts[("Constructor", "Screw")], 3)
        self.assertEqual(counts[("Constructor", "Iron Rod")], 2)
        self.assertEqual(counts[("Smelter", "Iron Ingot")], 1)

    def test_screws_chain_bom(self):
        result = plan("Desc_IronScrew_C", 120.0, self.recipes)
        # 1 Smelter at 30/min consumes 30 Iron Ore/min
        self.assertAlmostEqual(result.bom["Desc_OreIron_C"], 30.0, places=4)

    def test_raw_ore_is_leaf_not_machine(self):
        result = plan("Desc_IronScrew_C", 120.0, self.recipes)
        machines = {r.machine_type for r in result.token_rows}
        # No miner should appear as a manufacturer row
        self.assertNotIn("Miner", machines)
        self.assertIn("Desc_OreIron_C", result.bom)

    def test_standard_preferred_over_alternate(self):
        # Both Recipe_Screw_C (standard) and Cast Screw (alternate) make screws.
        result = plan("Desc_IronScrew_C", 120.0, self.recipes)
        screw_row = next(r for r in result.token_rows if "Screw" in r.recipe_name)
        self.assertEqual(screw_row.recipe_name, "Screw")  # not "Alternate: Cast Screw"

    def test_alternate_selected_when_requested(self):
        result = plan("Desc_IronScrew_C", 120.0, self.recipes,
                      prefer_alternate={"Recipe_Alternate_CastScrew_C"})
        screw_row = next(r for r in result.token_rows if "Screw" in r.recipe_name)
        self.assertEqual(screw_row.recipe_name, "Alternate: Cast Screw")

    def test_fluid_normalization(self):
        # Alumina Solution consumes Water Amount 18000 (=18 m3) and produces
        # AluminaSolution 12000 (=12 m3). load_recipes divides fluids by 1000.
        recipe = next(r for r in self.recipes if r.class_name == "Recipe_AluminaSolution_C")
        water = dict(recipe.ingredients)["Desc_Water_C"]
        alumina = dict(recipe.products)["Desc_AluminaSolution_C"]
        self.assertAlmostEqual(water, 18.0, places=4)
        self.assertAlmostEqual(alumina, 12.0, places=4)

    def test_overproduction_surfaced(self):
        # 50 screws/min: 50/40 -> ceil = 2 machines -> 80/min actual -> 30 slack
        result = plan("Desc_IronScrew_C", 50.0, self.recipes)
        screw_row = next(r for r in result.token_rows if "Screw" in r.recipe_name)
        self.assertEqual(screw_row.count, 2)
        self.assertAlmostEqual(screw_row.overproduction, 30.0, places=4)


class NLParseTests(unittest.TestCase):
    def test_build_at_rate(self):
        item, rate = parse_command("build screws at 120/min")
        self.assertEqual(item, "Desc_IronScrew_C")
        self.assertEqual(rate, 120.0)

    def test_per_minute_phrasing(self):
        item, rate = parse_command("iron rods @ 60 per minute")
        self.assertEqual(item, "Desc_IronRod_C")
        self.assertEqual(rate, 60.0)

    def test_rate_missing_raises(self):
        with self.assertRaises(ValueError):
            parse_command("just build screws")


class FRMAndSitingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockFRMServer().__enter__()
        cls.client = FRMClient("127.0.0.1", cls.server.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_resource_nodes_parsed(self):
        nodes = self.client.resource_nodes()
        self.assertEqual(len(nodes), 6)
        iron = [n for n in nodes if n.item_class == "Desc_OreIron_C"]
        self.assertEqual(len(iron), 3)

    def test_detect_miner_tier(self):
        self.assertEqual(self.client.detect_miner_tier(), 3)

    def test_discovered_filtering_excludes_undiscovered(self):
        nodes = self.client.resource_nodes()
        towers = self.client.radar_towers()
        extractors = self.client.placed_extractors()
        disc = discovered_nodes(nodes, extractors, towers)

        # The impure iron node at (500000,500000) is outside radar and has no
        # miner -> must be excluded. The other 5 are discovered.
        self.assertEqual(len(disc), 5)
        far = [n for n in disc if n.x == 500000]
        self.assertEqual(far, [])

    def test_discovered_via_radar(self):
        nodes = self.client.resource_nodes()
        towers = self.client.radar_towers()
        disc = discovered_nodes(nodes, [], towers)
        # Pure iron at (5000,0) is within the 150000 radar radius
        self.assertTrue(any(n.x == 5000 for n in disc))

    def test_discovered_via_extractor_only(self):
        nodes = self.client.resource_nodes()
        extractors = self.client.placed_extractors()
        # No radar towers; only the Mk3 miner near (200000,0) discovers a node
        disc = discovered_nodes(nodes, extractors, [])
        xs = {n.x for n in disc}
        self.assertIn(200000, xs)
        self.assertNotIn(5000, xs)  # pure node has no miner, no radar -> hidden

    def test_siting_picks_pure_node(self):
        nodes = self.client.resource_nodes()
        towers = self.client.radar_towers()
        extractors = self.client.placed_extractors()
        disc = discovered_nodes(nodes, extractors, towers)

        bom = {"Desc_OreIron_C": 30.0}
        site = find_site(bom, disc, footprint_width_uu=800, footprint_length_uu=1800)
        # The Pure iron node (highest purity weight) at (5000,0) should be the
        # one assigned to cover the iron demand.
        iron_assignments = [a for a in site.assignments
                            if a.item_class == "Desc_OreIron_C"]
        self.assertEqual(len(iron_assignments), 1)
        self.assertEqual(iron_assignments[0].node.x, 5000)
        self.assertEqual(iron_assignments[0].node.purity, Purity.PURE)
        self.assertEqual(site.material_gap, {})  # 30/min fully covered
        # Build center is the centroid of the discovered cluster near the node
        self.assertTrue(0 <= site.center_x <= 10000)


class MinerPlanTests(unittest.TestCase):
    def test_pure_node_exact_clock(self):
        # 30/min Iron Ore from a single Pure node, Mk3 miner (480/min base):
        #   clock = 30/480 * 100 = 6.25%
        from world_state import ResourceNode
        node = ResourceNode("Desc_OreIron_C", Purity.PURE, 5000, 0, 100)
        mp = plan_miners({"Desc_OreIron_C": 30.0}, [node], miner_tier=3)
        self.assertEqual(len(mp.assignments), 1)
        a = mp.assignments[0]
        self.assertEqual(a.miner_tier, 3)
        self.assertAlmostEqual(a.clock_pct, 6.25, places=2)
        self.assertAlmostEqual(a.rate_per_min, 30.0, places=2)

    def test_tier_cap_respected(self):
        # Same node but only Mk1 unlocked (120/min base): 30/120 = 25%
        from world_state import ResourceNode
        node = ResourceNode("Desc_OreIron_C", Purity.PURE, 5000, 0, 100)
        mp = plan_miners({"Desc_OreIron_C": 30.0}, [node], miner_tier=1)
        a = mp.assignments[0]
        self.assertEqual(a.miner_tier, 1)
        self.assertAlmostEqual(a.clock_pct, 25.0, places=2)

    def test_multi_node_overflow(self):
        # Need 600/min, one Pure Mk3 node maxes at 480*2.5=1200... so one node
        # at exact clock. Use a demand that needs two nodes: 1500/min.
        from world_state import ResourceNode
        n1 = ResourceNode("Desc_OreIron_C", Purity.PURE, 0, 0, 0)
        n2 = ResourceNode("Desc_OreIron_C", Purity.PURE, 100000, 0, 0)
        mp = plan_miners({"Desc_OreIron_C": 1500.0}, [n1, n2], miner_tier=3)
        # First node flat out at 250% = 1200/min, second covers remaining 300.
        self.assertEqual(len(mp.assignments), 2)
        self.assertAlmostEqual(mp.assignments[0].clock_pct, 250.0, places=2)
        self.assertAlmostEqual(mp.assignments[0].rate_per_min, 1200.0, places=2)
        self.assertAlmostEqual(mp.assignments[1].rate_per_min, 300.0, places=2)

    def test_uncovered_when_no_nodes(self):
        mp = plan_miners({"Desc_OreCopper_C": 60.0}, [], miner_tier=3)
        self.assertIn("Desc_OreCopper_C", mp.uncovered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
