"""
siting.py

Siting optimizer (spec §4.2).

Given:
  - a bill of materials (raw item → /min required)
  - all resource nodes in the world (from world_state.py)
  - machine counts + geometry (factory_geometry.py)

Finds the best build location by scoring candidate sites:
  score = sum over raw inputs of (purity_weight * available_rate / needed_rate)
  tie-break: distance from player (prefer closer)

Purity weights: Impure=1, Normal=2, Pure=4 (relative extractor output ratios).
Extractor base rates (/min): Impure=30, Normal=60, Pure=120 (mk1 miner, solid).
Fluid extractors (oil): Impure=150, Normal=300, Pure=600 m³/min.

The result is a SiteReport with the chosen world coordinates, the node
cluster that satisfies the BOM, and the material gap (what still needs to
come from elsewhere — e.g. player inventory or existing factory bus).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from world_state import ResourceNode, Purity, StorageItem

PURITY_WEIGHT: dict[Purity, float] = {
    Purity.IMPURE: 1.0,
    Purity.NORMAL: 2.0,
    Purity.PURE:   4.0,
}

# Base extraction rate /min for mk1 machines at each purity
SOLID_EXTRACTOR_RATE: dict[Purity, float] = {
    Purity.IMPURE: 30.0,
    Purity.NORMAL: 60.0,
    Purity.PURE:   120.0,
}
FLUID_EXTRACTOR_RATE: dict[Purity, float] = {
    Purity.IMPURE: 150.0,
    Purity.NORMAL: 300.0,
    Purity.PURE:   600.0,
}

FLUID_RAW: frozenset[str] = frozenset({"Desc_LiquidOil_C", "Desc_Water_C", "Desc_NitrogenGas_C"})


def extractor_rate(item_class: str, purity: Purity) -> float:
    if item_class in FLUID_RAW:
        return FLUID_EXTRACTOR_RATE[purity]
    return SOLID_EXTRACTOR_RATE[purity]


@dataclass
class NodeAssignment:
    node: ResourceNode
    item_class: str
    supplied_rate: float        # /min this node provides toward the BOM


@dataclass
class SiteReport:
    center_x: float             # world X of build center
    center_y: float             # world Y
    center_z: float             # world Z (elevation, for reference)
    score: float
    assignments: list[NodeAssignment]
    material_gap: dict[str, float]   # items still short after node coverage
    footprint_width_uu: float        # reserved ground width (Unreal units)
    footprint_length_uu: float       # reserved ground depth


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def find_site(
    bom: dict[str, float],
    nodes: list[ResourceNode],
    footprint_width_uu: float,
    footprint_length_uu: float,
    player_x: float = 0.0,
    player_y: float = 0.0,
    inventory: Optional[list[StorageItem]] = None,
) -> SiteReport:
    """Find the best build site for the given BOM.

    Strategy:
      For each node that supplies a needed raw resource, compute a score.
      Group nearby nodes (within cluster_radius) and treat the group as one
      candidate site.  Pick the highest-scoring group.

    cluster_radius is generous (5000 uu = 50 m) — adjust if nodes are sparse.
    """
    if not bom:
        return SiteReport(
            center_x=player_x, center_y=player_y, center_z=0.0,
            score=0.0, assignments=[],
            material_gap={},
            footprint_width_uu=footprint_width_uu,
            footprint_length_uu=footprint_length_uu,
        )

    # Subtract inventory/storage from BOM to get actual need
    inv_stock: dict[str, float] = {}
    for si in (inventory or []):
        inv_stock[si.item_class] = inv_stock.get(si.item_class, 0.0) + si.amount

    # Cluster nodes by proximity
    CLUSTER_RADIUS = 5000.0  # uu

    clusters: list[list[ResourceNode]] = []
    assigned_to: dict[int, int] = {}  # node index → cluster index

    for i, node in enumerate(nodes):
        placed = False
        for ci, cluster in enumerate(clusters):
            rep = cluster[0]
            if _distance(node.x, node.y, rep.x, rep.y) <= CLUSTER_RADIUS:
                cluster.append(node)
                assigned_to[i] = ci
                placed = True
                break
        if not placed:
            assigned_to[i] = len(clusters)
            clusters.append([node])

    best_score = -1.0
    best_cluster: list[ResourceNode] = []

    for cluster in clusters:
        score = 0.0
        for node in cluster:
            needed = bom.get(node.item_class, 0.0)
            if needed <= 0:
                continue
            rate = extractor_rate(node.item_class, node.purity)
            score += PURITY_WEIGHT[node.purity] * min(rate, needed) / needed

        # Tie-break: prefer closer to player
        cx = sum(n.x for n in cluster) / len(cluster)
        cy = sum(n.y for n in cluster) / len(cluster)
        dist = _distance(cx, cy, player_x, player_y)
        dist_penalty = dist / 1_000_000.0  # small, just for tie-breaking

        adjusted = score - dist_penalty
        if adjusted > best_score:
            best_score = adjusted
            best_cluster = cluster

    if not best_cluster:
        return SiteReport(
            center_x=player_x, center_y=player_y, center_z=0.0,
            score=0.0, assignments=[],
            material_gap=dict(bom),
            footprint_width_uu=footprint_width_uu,
            footprint_length_uu=footprint_length_uu,
        )

    # Build assignments for the winning cluster
    remaining: dict[str, float] = dict(bom)
    assignments: list[NodeAssignment] = []
    for node in best_cluster:
        if node.item_class not in remaining or remaining[node.item_class] <= 0:
            continue
        rate = extractor_rate(node.item_class, node.purity)
        supplied = min(rate, remaining[node.item_class])
        remaining[node.item_class] -= supplied
        assignments.append(NodeAssignment(node=node, item_class=node.item_class,
                                          supplied_rate=supplied))

    cx = sum(n.x for n in best_cluster) / len(best_cluster)
    cy = sum(n.y for n in best_cluster) / len(best_cluster)
    cz = sum(n.z for n in best_cluster) / len(best_cluster)

    # Material gap = what's still needed after node coverage and inventory
    gap: dict[str, float] = {}
    for item, need in remaining.items():
        if need <= 1e-6:
            continue
        stock = inv_stock.get(item, 0.0)
        shortfall = need - stock
        if shortfall > 1e-6:
            gap[item] = shortfall

    return SiteReport(
        center_x=cx, center_y=cy, center_z=cz,
        score=best_score,
        assignments=assignments,
        material_gap=gap,
        footprint_width_uu=footprint_width_uu,
        footprint_length_uu=footprint_length_uu,
    )


def format_site(report: SiteReport) -> str:
    lines = [
        "SITE",
        "-" * 40,
        f"  Location:  X={report.center_x:.0f}  Y={report.center_y:.0f}  Z={report.center_z:.0f} (uu)",
        f"  Score:     {report.score:.3f}",
        f"  Footprint: {report.footprint_width_uu/100:.0f}m wide x {report.footprint_length_uu/100:.0f}m deep",
        "",
        "  Node assignments:",
    ]
    for a in report.assignments:
        lines.append(
            f"    {a.item_class:<35}  {a.node.purity.name:<7}  "
            f"{a.supplied_rate:.1f}/min"
        )
    if report.material_gap:
        lines += ["", "  MATERIAL GAP (needs to come from bus / inventory):"]
        for item, shortfall in sorted(report.material_gap.items(), key=lambda x: -x[1]):
            lines.append(f"    {item:<40}  {shortfall:.1f}/min SHORT")
    else:
        lines.append("  All raw inputs covered by nearby nodes.")
    return "\n".join(lines)
