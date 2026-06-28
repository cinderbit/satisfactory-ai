"""
miner_planner.py

Miner / extractor planning layer.

Given:
  - a BOM of raw resources (item_class → /min required)
  - available resource nodes from FRM (ResourceNode list)
  - the highest unlocked miner/extractor tier

Computes for each raw resource:
  - which nodes to use
  - miner tier (capped at what's unlocked)
  - exact clock % to hit the required rate with minimal waste
  - total extraction rate and any overproduction

Philosophy: make the most of what you have.
  - Never suggest a tier the player hasn't unlocked.
  - Prefer fewer miners at higher clock over more miners at lower clock.
  - Aim for exact rate; overproduce as little as possible.
  - Overclock cap is 250%. Underclock is allowed (down to 1%) for precision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from world_state import ResourceNode, Purity

# ---------------------------------------------------------------------------
# Base extraction rates (/min) at 100% clock, per tier per purity
# ---------------------------------------------------------------------------

# Solid miners (Mk1 / Mk2 / Mk3)
MINER_BASE: dict[int, dict[Purity, float]] = {
    1: {Purity.IMPURE: 30.0,  Purity.NORMAL: 60.0,  Purity.PURE: 120.0},
    2: {Purity.IMPURE: 60.0,  Purity.NORMAL: 120.0, Purity.PURE: 240.0},
    3: {Purity.IMPURE: 120.0, Purity.NORMAL: 240.0, Purity.PURE: 480.0},
}

# Water extractor (one tier)
WATER_EXTRACTOR_BASE = 120.0   # m³/min at 100%

# Resource extractor (oil, nitrogen — same machine, one tier)
RESOURCE_EXTRACTOR_BASE: dict[Purity, float] = {
    Purity.IMPURE: 150.0,
    Purity.NORMAL: 300.0,
    Purity.PURE:   600.0,
}

OVERCLOCK_MAX = 2.5    # 250%
OVERCLOCK_MIN = 0.01   # 1%

# Items extracted by the resource extractor (not the miner)
FLUID_EXTRACTABLES: frozenset[str] = frozenset({
    "Desc_LiquidOil_C",
    "Desc_NitrogenGas_C",
})
WATER_CLASS = "Desc_Water_C"


def _max_rate(item_class: str, purity: Purity, miner_tier: int) -> float:
    """Max /min a single extractor of the given tier can produce at 250% clock."""
    if item_class == WATER_CLASS:
        return WATER_EXTRACTOR_BASE * OVERCLOCK_MAX
    if item_class in FLUID_EXTRACTABLES:
        return RESOURCE_EXTRACTOR_BASE[purity] * OVERCLOCK_MAX
    return MINER_BASE[miner_tier][purity] * OVERCLOCK_MAX


def _base_rate(item_class: str, purity: Purity, miner_tier: int) -> float:
    if item_class == WATER_CLASS:
        return WATER_EXTRACTOR_BASE
    if item_class in FLUID_EXTRACTABLES:
        return RESOURCE_EXTRACTOR_BASE[purity]
    return MINER_BASE[miner_tier][purity]


def _extractor_type(item_class: str) -> str:
    if item_class == WATER_CLASS:
        return "WaterExtractor"
    if item_class in FLUID_EXTRACTABLES:
        return "ResourceExtractor"
    return "Miner"


@dataclass
class MinerAssignment:
    node: ResourceNode
    item_class: str
    extractor_type: str        # "Miner" | "WaterExtractor" | "ResourceExtractor"
    miner_tier: int            # 1/2/3 (always 1 for water/resource extractor)
    clock_pct: float           # 1–250
    rate_per_min: float        # actual output at this clock


@dataclass
class MinerPlan:
    assignments: list[MinerAssignment]
    total_rates: dict[str, float]      # item_class → total /min produced
    overproduction: dict[str, float]   # item_class → surplus /min
    uncovered: dict[str, float]        # item_class → /min still short (no nodes)


def plan_miners(
    bom: dict[str, float],
    nodes: list[ResourceNode],
    miner_tier: int = 3,
) -> MinerPlan:
    """Assign miners to nodes to satisfy the BOM.

    For each raw resource in the BOM:
      1. Collect all available nodes of that resource type, sorted best-first
         (Pure > Normal > Impure, then by max rate desc).
      2. Greedily assign nodes until the required rate is met.
      3. The last node assigned gets an exact clock % to hit the target
         precisely; earlier nodes run at 250% to maximise throughput.

    miner_tier: highest unlocked miner tier (1, 2, or 3). Never exceeds this.
    """
    miner_tier = max(1, min(3, miner_tier))

    assignments: list[MinerAssignment] = []
    total_rates: dict[str, float] = {}
    overproduction: dict[str, float] = {}
    uncovered: dict[str, float] = {}

    # Group nodes by item class
    nodes_by_item: dict[str, list[ResourceNode]] = {}
    for node in nodes:
        nodes_by_item.setdefault(node.item_class, []).append(node)

    for item_class, needed in bom.items():
        available = nodes_by_item.get(item_class, [])
        if not available:
            uncovered[item_class] = needed
            continue

        # Sort: Pure first, then by max extractable rate descending
        tier = miner_tier if _extractor_type(item_class) == "Miner" else 1
        available_sorted = sorted(
            available,
            key=lambda n: (n.purity.value, _max_rate(item_class, n.purity, tier)),
            reverse=True,
        )

        remaining = needed
        item_assignments: list[MinerAssignment] = []

        for node in available_sorted:
            if remaining <= 1e-6:
                break

            base = _base_rate(item_class, node.purity, tier)
            max_r = base * OVERCLOCK_MAX

            if max_r <= 1e-9:
                continue

            if remaining >= max_r:
                # Run this node flat out at 250%
                clock = OVERCLOCK_MAX * 100
                rate = max_r
            else:
                # This node is enough — set exact clock
                clock = (remaining / base) * 100
                clock = max(OVERCLOCK_MIN * 100, min(OVERCLOCK_MAX * 100, clock))
                rate = base * (clock / 100)

            item_assignments.append(MinerAssignment(
                node=node,
                item_class=item_class,
                extractor_type=_extractor_type(item_class),
                miner_tier=tier,
                clock_pct=round(clock, 2),
                rate_per_min=round(rate, 4),
            ))
            remaining -= rate

        assignments.extend(item_assignments)
        produced = sum(a.rate_per_min for a in item_assignments)
        total_rates[item_class] = produced

        if remaining > 1e-6:
            uncovered[item_class] = remaining
        surplus = produced - needed
        if surplus > 1e-6:
            overproduction[item_class] = surplus

    return MinerPlan(
        assignments=assignments,
        total_rates=total_rates,
        overproduction=overproduction,
        uncovered=uncovered,
    )


def format_miner_plan(plan: MinerPlan, bom: dict[str, float]) -> str:
    lines = ["MINERS / EXTRACTORS", "-" * 40]

    by_item: dict[str, list[MinerAssignment]] = {}
    for a in plan.assignments:
        by_item.setdefault(a.item_class, []).append(a)

    for item_class, needed in sorted(bom.items()):
        item_assignments = by_item.get(item_class, [])
        produced = plan.total_rates.get(item_class, 0.0)
        short = plan.uncovered.get(item_class, 0.0)

        lines.append(f"\n  {item_class}  (need {needed:.1f}/min → producing {produced:.1f}/min)")
        if not item_assignments:
            lines.append(f"    !! NO NODES FOUND — {short:.1f}/min uncovered")
            continue

        for a in item_assignments:
            loc = a.node
            lines.append(
                f"    {a.extractor_type} Mk{a.miner_tier}  "
                f"{a.node.purity.name:<7}  "
                f"@ {a.clock_pct:.1f}%  "
                f"→ {a.rate_per_min:.1f}/min  "
                f"[X={loc.x:.0f} Y={loc.y:.0f} Z={loc.z:.0f}]"
            )

        if short > 1e-6:
            lines.append(f"    !! Still {short:.1f}/min SHORT — not enough nodes nearby")
        elif plan.overproduction.get(item_class, 0) > 1e-6:
            lines.append(f"    (+{plan.overproduction[item_class]:.1f}/min overproduction — clock down last miner to reduce)")

    return "\n".join(lines)
