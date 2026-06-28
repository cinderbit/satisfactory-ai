"""
recipe_planner.py

Recipe-graph planner (spec §4.1).

Loads a normalized recipe JSON, builds a dependency DAG from a target item +
rate, and emits:
  - token_rows: list of {count, machineType, recipe, rate_per_min}
  - bom:        dict of {raw_resource: required_rate_per_min}

Expected recipe JSON schema (one entry per recipe):
{
  "ClassName":             "Recipe_IronIngot_C",
  "DisplayName":           "Iron Ingot",
  "Ingredients":           [{"Item": "Desc_OreIron_C", "Amount": 1}],
  "Products":              [{"Item": "Desc_IronIngot_C", "Amount": 1}],
  "ManufacturingDuration": 2.0,
  "ProducedIn":            ["Build_SmelterMk1_C"],
  "IsAlternate":           false
}

Fluid amounts in the export are ×1000; set fluid_scale=1000 (default) to
normalize.  The planner multiplies amounts by that scale before rate math.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Raw-resource leaves: traversal stops here (spec §5 rule 1)
# ---------------------------------------------------------------------------
RAW_RESOURCES: frozenset[str] = frozenset({
    # Miners
    "Desc_OreIron_C", "Desc_OreCopper_C", "Desc_Stone_C", "Desc_Coal_C",
    "Desc_OreGold_C", "Desc_Sulfur_C", "Desc_RawQuartz_C", "Desc_OreBauxite_C",
    "Desc_OreUranium_C", "Desc_SAM_C",
    # Extractors
    "Desc_LiquidOil_C",
    "Desc_Water_C",
    # Nitrogen (extractor, 1.0+)
    "Desc_NitrogenGas_C",
})

# ---------------------------------------------------------------------------
# ProducedIn class → machine enum (spec §5 rule 3)
# ---------------------------------------------------------------------------
MACHINE_MAP: dict[str, str] = {
    "Build_SmelterMk1_C":              "Smelter",
    "Build_ConstructorMk1_C":          "Constructor",
    "Build_AssemblerMk1_C":            "Assembler",
    "Build_FoundryMk1_C":              "Foundry",
    "Build_ManufacturerMk1_C":         "Manufacturer",
    "Build_OilRefinery_C":             "OilRefinery",
    "Build_Blender_C":                 "Blender",
    "Build_HadronCollider_C":          "ParticleAccelerator",
    "Build_QuantumEncoder_C":          "QuantumEncoder",
    "Build_Converter_C":               "Converter",
    "Build_Packager_C":                "Packager",
    "Build_GeneratorCoal_C":           "CoalGenerator",
    "Build_GeneratorFuel_C":           "FuelGenerator",
    "Build_GeneratorNuclear_C":        "NuclearReactor",
    # alternate class names found in some exports
    "FGBuildableManufacturerVariablePower": "ParticleAccelerator",
}

# Items treated as fluids (amounts ÷ fluid_scale before rate math)
FLUID_ITEMS: frozenset[str] = frozenset({
    "Desc_Water_C", "Desc_LiquidOil_C", "Desc_LiquidFuel_C",
    "Desc_LiquidBiofuel_C", "Desc_LiquidTurboFuel_C", "Desc_AluminaSolution_C",
    "Desc_SulfuricAcid_C", "Desc_NitricAcid_C", "Desc_DissolvedSilica_C",
    "Desc_NitrogenGas_C", "Desc_HeavyOilResidue_C",
})


@dataclass
class Recipe:
    class_name: str
    display_name: str
    ingredients: list[tuple[str, float]]   # (item_class, normalized_amount)
    products: list[tuple[str, float]]
    duration: float                        # seconds per cycle
    machine: str                           # machine enum name
    is_alternate: bool = False

    def rate_for(self, item_class: str) -> float:
        """Per-machine output rate (units/min) for a product."""
        for ic, amt in self.products:
            if ic == item_class:
                return amt / self.duration * 60.0
        raise KeyError(item_class)


@dataclass
class TokenRow:
    machine_type: str
    recipe_name: str
    count: int
    target_rate: float       # /min requested of this stage
    actual_rate: float       # /min produced (count * per_machine_rate)
    overproduction: float    # actual - target


@dataclass
class PlanResult:
    token_rows: list[TokenRow]
    bom: dict[str, float]           # raw resource → /min needed
    byproducts: dict[str, float]    # unclaimed outputs → /min produced


def load_recipes(path: str | Path, fluid_scale: float = 1000.0) -> list[Recipe]:
    """Load and normalize a recipe JSON export."""
    data = json.loads(Path(path).read_text())
    recipes: list[Recipe] = []
    for entry in data:
        produced_in = entry.get("ProducedIn", [])
        machine = None
        for p in produced_in:
            machine = MACHINE_MAP.get(p)
            if machine:
                break
        if machine is None:
            continue  # workbench, build gun, etc. — skip

        def norm(item: str, amt: float) -> float:
            return amt / fluid_scale if item in FLUID_ITEMS else amt

        ingredients = [
            (ing["Item"], norm(ing["Item"], ing["Amount"]))
            for ing in entry.get("Ingredients", [])
        ]
        products = [
            (p["Item"], norm(p["Item"], p["Amount"]))
            for p in entry.get("Products", [])
        ]

        recipes.append(Recipe(
            class_name=entry["ClassName"],
            display_name=entry.get("DisplayName", entry["ClassName"]),
            ingredients=ingredients,
            products=products,
            duration=float(entry["ManufacturingDuration"]),
            machine=machine,
            is_alternate=bool(entry.get("IsAlternate", False)),
        ))
    return recipes


def _build_index(
    recipes: list[Recipe],
    prefer_alternate: set[str] | None = None,
) -> dict[str, Recipe]:
    """Map item_class → best recipe for that item.

    Standard recipes win unless an alternate class name appears in
    prefer_alternate.  Among multiple standards the first encountered wins
    (export order is stable).
    """
    prefer_alternate = prefer_alternate or set()
    index: dict[str, Recipe] = {}

    for recipe in recipes:
        for item_class, _ in recipe.products:
            if item_class in RAW_RESOURCES:
                continue
            existing = index.get(item_class)
            if existing is None:
                index[item_class] = recipe
            else:
                # prefer an explicitly-requested alternate
                if recipe.class_name in prefer_alternate and existing.class_name not in prefer_alternate:
                    index[item_class] = recipe
                # otherwise prefer standard over alternate
                elif not recipe.is_alternate and existing.is_alternate:
                    index[item_class] = recipe
    return index


def plan(
    target_item: str,
    target_rate: float,
    recipes: list[Recipe],
    prefer_alternate: set[str] | None = None,
) -> PlanResult:
    """Build a production plan for target_item at target_rate /min.

    Returns token rows (deepest dependency first) and a BOM of raw inputs.
    """
    index = _build_index(recipes, prefer_alternate)

    # Accumulated demand: item_class → total /min needed
    demand: dict[str, float] = defaultdict(float)
    demand[target_item] = target_rate

    # Byproducts accumulate here and can offset upstream demand
    byproducts: dict[str, float] = defaultdict(float)

    visited_order: list[str] = []
    visited: set[str] = set()
    bom: dict[str, float] = {}

    queue: list[str] = [target_item]
    cycle_guard: set[str] = set()

    while queue:
        item = queue.pop(0)
        if item in visited:
            continue
        visited.add(item)
        visited_order.append(item)

        if item in RAW_RESOURCES:
            bom[item] = demand[item]
            continue

        recipe = index.get(item)
        if recipe is None:
            # Treat as raw leaf if no recipe found
            bom[item] = demand[item]
            continue

        assert item not in cycle_guard, f"Cycle detected at {item}"
        cycle_guard.add(item)

        per_machine = recipe.rate_for(item)
        machines_needed = math.ceil(demand[item] / per_machine)
        actual_rate = machines_needed * per_machine

        # Register byproducts from this recipe
        for prod_item, prod_amt in recipe.products:
            if prod_item == item:
                continue
            bp_rate = prod_amt / recipe.duration * 60.0 * machines_needed
            byproducts[prod_item] += bp_rate

        # Propagate ingredient demand upstream
        for ing_item, ing_amt in recipe.ingredients:
            ing_rate_per_machine = ing_amt / recipe.duration * 60.0
            total_ing_needed = ing_rate_per_machine * machines_needed
            # Credit byproducts that cover this ingredient
            credit = min(byproducts.get(ing_item, 0.0), total_ing_needed)
            byproducts[ing_item] = byproducts.get(ing_item, 0.0) - credit
            net = total_ing_needed - credit
            if net > 1e-9:
                demand[ing_item] += net
                if ing_item not in visited:
                    queue.append(ing_item)

    # Build token rows in dependency order (deepest first = process order)
    token_rows: list[TokenRow] = []
    for item in visited_order:
        if item in RAW_RESOURCES or item not in index:
            continue
        recipe = index[item]
        per_machine = recipe.rate_for(item)
        count = math.ceil(demand[item] / per_machine)
        actual = count * per_machine
        token_rows.append(TokenRow(
            machine_type=recipe.machine,
            recipe_name=recipe.display_name,
            count=count,
            target_rate=demand[item],
            actual_rate=actual,
            overproduction=actual - demand[item],
        ))

    return PlanResult(
        token_rows=token_rows,
        bom=dict(bom),
        byproducts={k: v for k, v in byproducts.items() if v > 1e-9},
    )


def format_plan(result: PlanResult, target_item: str, target_rate: float) -> str:
    lines = [
        f"Production plan: {target_item} @ {target_rate:.1f}/min",
        "=" * 60,
        "",
        "MACHINES",
        "-" * 40,
    ]
    for row in result.token_rows:
        slack = f"  (+{row.overproduction:.1f}/min slack)" if row.overproduction > 0.01 else ""
        lines.append(
            f"  {row.count:3d}x {row.machine_type:<22} [{row.recipe_name}]"
            f"  → {row.actual_rate:.1f}/min{slack}"
        )

    lines += ["", "RAW INPUTS (BOM)", "-" * 40]
    for item, rate in sorted(result.bom.items(), key=lambda x: -x[1]):
        lines.append(f"  {item:<40} {rate:8.1f}/min")

    if result.byproducts:
        lines += ["", "BYPRODUCTS (unclaimed)", "-" * 40]
        for item, rate in sorted(result.byproducts.items(), key=lambda x: -x[1]):
            lines.append(f"  {item:<40} {rate:8.1f}/min")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: recipe_planner.py <recipes.json> <ItemClassName> <rate/min>")
        sys.exit(1)

    recipes = load_recipes(sys.argv[1])
    result = plan(sys.argv[2], float(sys.argv[3]), recipes)
    print(format_plan(result, sys.argv[2], float(sys.argv[3])))
