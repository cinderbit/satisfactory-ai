"""
blueprint_planner.py

Fit-check and auto-split for FactorySpawner blueprints.

FactorySpawner lays the machines from one /FactorySpawner command out as a
single strip: each comma-separated entry is a row of N machines along +X, and
rows stack along +Y with belt-routing reserve between them (see
factory_geometry.py). A strip therefore has:

    width  = max row width   (a row of N machines = N * machine_width)
    depth  = sum row depths   (each row reserves input+output routing length)

A blueprint can only be stamped if it fits inside a Blueprint Designer's build
area. The usable interior is an NxN foundation grid (8 m each):

    Mk.1 = 4x4 = 32 m,  Mk.2 = 5x5 = 40 m,  Mk.3 = 6x6 = 48 m

This module reports whether a plan fits a given designer as a single strip and,
when it doesn't, splits it into several designer-sized blueprints — each its own
/FactorySpawner command — by (1) splitting any row that is wider than the
designer into multiple shorter rows, then (2) packing rows into blueprints up to
the depth limit, keeping dependency-adjacent stages together where possible.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory_geometry import MACHINE_CONFIG, row_footprint
from recipe_planner import PlanResult, TokenRow

# Blueprint Designer interior build area, per tier, in meters (square footprint).
# Mk1 4x4, Mk2 5x5, Mk3 6x6 foundations of 8 m each.
DESIGNER_BUILD_AREA_M: dict[int, int] = {1: 32, 2: 40, 3: 48}

# Machine enum -> upstream FactorySpawner machine token (only divergence).
_SPAWNER_MACHINE = {"OilRefinery": "Refinery"}


def spawner_recipe_token(recipe_class: str, recipe_name: str = "") -> str:
    """FactorySpawner's recipe token = ClassName minus the Recipe_/_C wrapper,
    e.g. Recipe_IngotIron_C -> "IngotIron". Falls back to the spaces-stripped
    display name when no class is available."""
    if recipe_class:
        tok = recipe_class
        if tok.startswith("Recipe_"):
            tok = tok[len("Recipe_"):]
        if tok.endswith("_C"):
            tok = tok[:-len("_C")]
        return tok
    return recipe_name.replace(" ", "")


def spawner_machine_token(machine_type: str) -> str:
    return _SPAWNER_MACHINE.get(machine_type, machine_type)


@dataclass
class SpawnRow:
    """One row in a FactorySpawner strip: `count` machines of one type/recipe."""
    machine_type: str
    count: int
    recipe_class: str
    recipe_name: str

    @property
    def width_m(self) -> float:
        w_uu, _ = row_footprint(self.machine_type, self.count)
        return w_uu / 100.0

    @property
    def depth_m(self) -> float:
        _, l_uu = row_footprint(self.machine_type, 1)
        return l_uu / 100.0

    def command_part(self) -> str:
        machine = spawner_machine_token(self.machine_type)
        recipe = spawner_recipe_token(self.recipe_class, self.recipe_name)
        return f"{self.count} {machine} {recipe}".rstrip()


@dataclass
class Blueprint:
    rows: list[SpawnRow]

    @property
    def width_m(self) -> float:
        return max((r.width_m for r in self.rows), default=0.0)

    @property
    def depth_m(self) -> float:
        return sum(r.depth_m for r in self.rows)

    def command(self) -> str:
        return "/FactorySpawner " + ", ".join(r.command_part() for r in self.rows)


def rows_from_plan(result: PlanResult) -> list[SpawnRow]:
    return [
        SpawnRow(r.machine_type, r.count, r.recipe_class, r.recipe_name)
        for r in result.token_rows
    ]


def _machine_width_m(machine_type: str) -> float:
    return float(MACHINE_CONFIG[machine_type].width)


def strip_dims_m(rows: list[SpawnRow]) -> tuple[float, float]:
    """(width, depth) of the whole plan laid out as one FactorySpawner strip."""
    width = max((r.width_m for r in rows), default=0.0)
    depth = sum(r.depth_m for r in rows)
    return width, depth


def fit_report(rows: list[SpawnRow]) -> dict:
    """For each designer tier, whether the plan fits as a single strip."""
    width, depth = strip_dims_m(rows)
    tiers = {}
    smallest_single = None
    for tier in sorted(DESIGNER_BUILD_AREA_M):
        size = DESIGNER_BUILD_AREA_M[tier]
        fits = width <= size and depth <= size
        tiers[tier] = fits
        if fits and smallest_single is None:
            smallest_single = tier
    return {
        "width_m": width,
        "depth_m": depth,
        "tiers": tiers,
        "smallest_single_tier": smallest_single,
    }


def _split_row_to_width(row: SpawnRow, size_m: int) -> tuple[list[SpawnRow], bool]:
    """Split one row so each sub-row is no wider than size_m. Returns the
    sub-rows and whether a single machine is itself too wide to ever fit."""
    mw = _machine_width_m(row.machine_type)
    if mw > size_m:
        # Even one machine won't fit this designer; emit as-is and flag it.
        return [row], True
    max_per_row = max(1, int(size_m // mw))
    if row.count <= max_per_row:
        return [row], False
    sub: list[SpawnRow] = []
    remaining = row.count
    while remaining > 0:
        n = min(max_per_row, remaining)
        sub.append(SpawnRow(row.machine_type, n, row.recipe_class, row.recipe_name))
        remaining -= n
    return sub, False


def split_for_tier(rows: list[SpawnRow], tier: int) -> tuple[list[Blueprint], list[str]]:
    """Split a plan into blueprints that each fit the given designer tier.

    Returns (blueprints, warnings). Warnings flag machines too wide for the tier.
    """
    size = DESIGNER_BUILD_AREA_M[tier]
    warnings: list[str] = []

    # 1. width-split rows so none exceeds the designer width
    sub_rows: list[SpawnRow] = []
    for row in rows:
        parts, too_wide = _split_row_to_width(row, size)
        if too_wide:
            warnings.append(
                f"{spawner_machine_token(row.machine_type)} is "
                f"{_machine_width_m(row.machine_type):.0f}m wide - does not fit a "
                f"Mk{tier} designer ({size}m). Use a larger designer."
            )
        sub_rows.extend(parts)

    # 2. depth-pack rows into blueprints (dependency order preserved)
    blueprints: list[Blueprint] = []
    current: list[SpawnRow] = []
    cur_depth = 0.0
    for r in sub_rows:
        if current and cur_depth + r.depth_m > size:
            blueprints.append(Blueprint(current))
            current = []
            cur_depth = 0.0
        current.append(r)
        cur_depth += r.depth_m
    if current:
        blueprints.append(Blueprint(current))
    return blueprints, warnings


def format_command(rows: list[SpawnRow]) -> str:
    """Single /FactorySpawner command for the given rows (no splitting)."""
    return "/FactorySpawner " + ", ".join(r.command_part() for r in rows)


def format_blueprint_plan(result: PlanResult, tier: int | None = None) -> str:
    """Human-readable fit report + the command(s) to paste.

    If the plan fits a single designer, prints that one command and the smallest
    tier that holds it. Otherwise splits for `tier` (default: Mk3) and prints one
    command per blueprint.
    """
    rows = rows_from_plan(result)
    if not rows:
        return "No machines to place."

    rep = fit_report(rows)
    lines = [
        "BLUEPRINT",
        "-" * 40,
        f"  Strip footprint: {rep['width_m']:.0f}m wide x {rep['depth_m']:.0f}m deep",
    ]
    for t in sorted(DESIGNER_BUILD_AREA_M):
        mark = "fits" if rep["tiers"][t] else "no"
        lines.append(f"    Mk{t} designer ({DESIGNER_BUILD_AREA_M[t]}m): {mark}")

    single = rep["smallest_single_tier"]
    if single is not None and tier is None:
        lines += [
            "",
            f"  Fits a Mk{single} designer as one blueprint. Paste:",
            f"    {format_command(rows)}",
        ]
        return "\n".join(lines)

    # Need to split (either it doesn't fit any single designer, or a tier was forced)
    use_tier = tier or 3
    blueprints, warnings = split_for_tier(rows, use_tier)
    fits_word = "forced" if tier else "does not fit a single designer"
    lines += [
        "",
        f"  Plan {fits_word} - splitting for Mk{use_tier} "
        f"({DESIGNER_BUILD_AREA_M[use_tier]}m) into {len(blueprints)} blueprint(s).",
        "  Stamp each, then belt them together:",
    ]
    for i, bp in enumerate(blueprints, 1):
        lines.append(
            f"    [BP {i}] {bp.width_m:.0f}m x {bp.depth_m:.0f}m")
        lines.append(f"      {bp.command()}")
    for w in warnings:
        lines.append(f"  [WARN] {w}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Demo with the screws @120/min plan shape (no game needed).
    from recipe_planner import TokenRow as _TR
    demo = PlanResult(
        token_rows=[
            _TR("Constructor", "Screws", 3, 120, 120, 0, "Recipe_Screw_C"),
            _TR("Constructor", "Iron Rod", 2, 30, 30, 0, "Recipe_IronRod_C"),
            _TR("Smelter", "Iron Ingot", 1, 30, 30, 0, "Recipe_IngotIron_C"),
        ],
        bom={"Desc_OreIron_C": 30.0},
        byproducts={},
    )
    print(format_blueprint_plan(demo))
