"""
advisor.py

Approval-gate CLI advisor (spec §4.4, §6 step 4).

Usage:
  python advisor.py --recipes recipes.json "build screws at 120/min"
  python advisor.py --recipes recipes.json --frm-host 192.168.1.10 \
                    "build iron rods at 60/min"

The advisor:
  1. Parses the natural-language build order (item + rate).
  2. Runs the recipe-graph planner to get token rows + BOM.
  3. Optionally queries FRM for resource nodes and picks a site.
  4. Prints the full plan (machines, counts, site, material gap).
  5. Waits for APPROVE / REJECT / MODIFY before doing anything.
  6. On approval: prints the FactorySpawner command tokens (ready to paste
     into chat, or for the mod's future HTTP endpoint).

This is a complete, useful product with ZERO new C++ (spec §6 step 4 milestone).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from recipe_planner import load_recipes, plan, format_plan, PlanResult
from factory_geometry import MACHINE_CONFIG, row_footprint, port_variant_index
from world_state import FRMClient, availability_check
from siting import find_site, format_site, SiteReport
from miner_planner import plan_miners, format_miner_plan, MinerPlan

# ---------------------------------------------------------------------------
# Natural-language parse: item name + rate
# ---------------------------------------------------------------------------

# Mapping of common spoken names → Desc_ class names
ITEM_NAME_MAP: dict[str, str] = {
    # Common items (expand as needed; ideally auto-built from recipe display names)
    "iron ore":          "Desc_OreIron_C",
    "copper ore":        "Desc_OreCopper_C",
    "limestone":         "Desc_Stone_C",
    "coal":              "Desc_Coal_C",
    "caterium ore":      "Desc_OreGold_C",
    "sulfur":            "Desc_Sulfur_C",
    "raw quartz":        "Desc_RawQuartz_C",
    "bauxite":           "Desc_OreBauxite_C",
    "uranium":           "Desc_OreUranium_C",
    "sam ore":           "Desc_SAM_C",
    "crude oil":         "Desc_LiquidOil_C",
    "water":             "Desc_Water_C",
    "iron ingot":        "Desc_IronIngot_C",
    "copper ingot":      "Desc_CopperIngot_C",
    "iron plate":        "Desc_IronPlate_C",
    "iron rod":          "Desc_IronRod_C",
    "screw":             "Desc_IronScrew_C",
    "screws":            "Desc_IronScrew_C",
    "wire":              "Desc_Wire_C",
    "cable":             "Desc_Cable_C",
    "concrete":          "Desc_Concrete_C",
    "reinforced iron plate": "Desc_IronPlateReinforced_C",
    "rotor":             "Desc_Rotor_C",
    "modular frame":     "Desc_ModularFrame_C",
    "copper sheet":      "Desc_CopperSheet_C",
    "steel ingot":       "Desc_SteelIngot_C",
    "steel beam":        "Desc_SteelPlate_C",
    "steel pipe":        "Desc_SteelPipe_C",
    "encased industrial beam": "Desc_SteelPlateReinforced_C",
    "motor":             "Desc_Motor_C",
    "heavy modular frame": "Desc_ModularFrameHeavy_C",
    "plastic":           "Desc_Plastic_C",
    "rubber":            "Desc_Rubber_C",
    "fuel":              "Desc_LiquidFuel_C",
    "computer":          "Desc_Computer_C",
    "circuit board":     "Desc_CircuitBoard_C",
    "ai limiter":        "Desc_CircuitBoardHighSpeed_C",
    "high-speed connector": "Desc_HighSpeedConnector_C",
    "supercomputer":     "Desc_ComputerSuper_C",
    "battery":           "Desc_Battery_C",
    "alclad aluminum sheet": "Desc_AluminumPlate_C",
    "aluminum ingot":    "Desc_AluminumIngot_C",
    "crystal oscillator": "Desc_CrystalOscillator_C",
    "radio control unit": "Desc_ModuleRDU_C",
    "magnetic field generator": "Desc_MagneticFieldGenerator_C",
    "assembly director system": "Desc_AssemblyDirectorSystem_C",
    "thermal propulsion rocket": "Desc_ThermalPropulsionRocket_C",
    "nuclear pasta":     "Desc_NuclearPasta_C",
}


def _fuzzy_lookup(name: str) -> Optional[str]:
    """Case-insensitive prefix/substring match against ITEM_NAME_MAP."""
    key = name.lower().strip()
    if key in ITEM_NAME_MAP:
        return ITEM_NAME_MAP[key]
    for k, v in ITEM_NAME_MAP.items():
        if key in k or k in key:
            return v
    return None


def parse_command(text: str) -> tuple[str, float]:
    """Extract (item_class, rate_per_min) from a natural-language command.

    Patterns recognised:
      "build screws at 120/min"
      "screws 120/min"
      "iron rods @ 60 per minute"
      "120/min of wire"
    """
    text = text.strip()

    # Extract rate: number followed by /min or per min or /minute
    rate_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:/\s*min(?:ute)?|per\s+min(?:ute)?)", text, re.I
    )
    if not rate_match:
        # Try bare number at end
        rate_match = re.search(r"(\d+(?:\.\d+)?)\s*$", text)
    if not rate_match:
        raise ValueError(f"Could not parse a rate from: {text!r}")

    rate = float(rate_match.group(1))

    # Remove rate and common filler words to isolate item name
    cleaned = text[: rate_match.start()] + text[rate_match.end() :]
    cleaned = re.sub(
        r"\b(build|make|produce|factory|at|@|of|for|a|an|the)\b", " ", cleaned, flags=re.I
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")

    item_class = _fuzzy_lookup(cleaned)
    if item_class is None:
        # Return as-is; let caller handle unknown item
        return cleaned, rate
    return item_class, rate


# ---------------------------------------------------------------------------
# Token-row formatting (the contract boundary with the mod)
# ---------------------------------------------------------------------------

def format_tokens(result: PlanResult, miner_plan: Optional[MinerPlan] = None) -> str:
    """Format token rows as JSON — ready for the mod's HTTP endpoint."""
    tokens = []

    # Miner / extractor tokens first (inputs before processors)
    if miner_plan:
        for a in miner_plan.assignments:
            tokens.append({
                "machineType": a.extractor_type,
                "minerTier":   a.miner_tier,
                "item":        a.item_class,
                "clockSpeed":  a.clock_pct,
                "nodeX":       a.node.x,
                "nodeY":       a.node.y,
                "nodeZ":       a.node.z,
            })

    for row in result.token_rows:
        tokens.append({
            "count":       row.count,
            "machineType": row.machine_type,
            "recipe":      row.recipe_name,
        })
    return json.dumps(tokens, indent=2)


def format_spawner_command(result: PlanResult) -> str:
    """Format as a /FactorySpawner chat command for manual pasting (step-4 milestone)."""
    parts = []
    for row in result.token_rows:
        parts.append(f"{row.count}x{row.machine_type}:{row.recipe_name}")
    return "/FactorySpawner " + " ".join(parts)


# ---------------------------------------------------------------------------
# Approval loop
# ---------------------------------------------------------------------------

def run_advisor(
    command: str,
    recipes_path: Optional[str],
    frm_host: Optional[str],
    frm_port: int,
    prefer_alternate: set[str],
    miner_tier: int = 3,
    non_interactive: bool = False,
) -> None:
    print(f"\n[Advisor] Parsing: {command!r}")

    # Parse item + rate
    try:
        item_class, rate = parse_command(command)
    except ValueError as e:
        print(f"[Error] {e}")
        sys.exit(1)

    print(f"[Advisor] Target: {item_class} @ {rate:.1f}/min\n")

    # Load recipes
    if recipes_path is None:
        print("[Warning] No --recipes file provided. Recipe planner skipped.")
        print("          Provide a normalized recipe JSON to generate a full plan.")
        print("          See recipe_parsing_notes.md for the expected format.")
        sys.exit(0)

    print("[Advisor] Loading recipes ...")
    recipes = load_recipes(recipes_path)
    print(f"          {len(recipes)} recipes loaded.")

    # Plan
    print("[Advisor] Planning production chain ...")
    result = plan(item_class, rate, recipes, prefer_alternate or None)

    print("\n" + format_plan(result, item_class, rate))

    # Compute footprint (use variant 0 = max ports; refine when recipe known)
    total_w = total_l = 0
    for row in result.token_rows:
        machine = row.machine_type
        if machine in MACHINE_CONFIG:
            w, l = row_footprint(machine, row.count)
            total_w = max(total_w, w)
            total_l += l

    print(f"\n  Est. total footprint: ~{total_w/100:.0f}m wide x {total_l/100:.0f}m deep")

    # Siting + miner planning (optional — needs FRM)
    site: Optional[SiteReport] = None
    miner_plan: Optional[MinerPlan] = None
    if frm_host:
        avail = availability_check(frm_host, frm_port)
        if avail.get("frm"):
            print(f"\n[Advisor] FRM reachable at {frm_host}:{frm_port}. Querying nodes ...")
            frm = FRMClient(frm_host, frm_port)
            try:
                nodes = frm.resource_nodes()
                print(f"          {len(nodes)} nodes found.")
                site = find_site(
                    bom=result.bom,
                    nodes=nodes,
                    footprint_width_uu=float(total_w),
                    footprint_length_uu=float(total_l),
                )
                print("\n" + format_site(site))

                # Miner planning: use only nodes near the chosen site
                site_nodes = site.assignments  # nodes already selected for this site
                nearby_nodes = [a.node for a in site_nodes]
                miner_plan = plan_miners(result.bom, nearby_nodes, miner_tier=miner_tier)
                print("\n" + format_miner_plan(miner_plan, result.bom))
            except Exception as e:
                print(f"[Warning] FRM query failed: {e}")
        else:
            print(f"[Warning] FRM not reachable at {frm_host}:{frm_port}. Siting skipped.")
    else:
        print("\n[Advisor] No --frm-host provided. Siting + miner planning skipped.")
        print("          Supply --frm-host to get node assignments and miner clock speeds.")

    # Approval gate
    print("\n" + "=" * 60)
    print("Approve this plan?  [yes / no / modify]")
    print("  yes    — output token rows / spawner command")
    print("  no     — abort")
    print("  modify — re-enter a new command")
    print("=" * 60)

    if non_interactive:
        answer = "yes"
        print("[non-interactive] auto-approved.")
    else:
        try:
            answer = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

    if answer.startswith("n"):
        print("Plan rejected. Exiting.")
        sys.exit(0)

    if answer.startswith("m"):
        new_cmd = input("New command: ").strip()
        run_advisor(new_cmd, recipes_path, frm_host, frm_port, prefer_alternate, miner_tier)
        return

    # Approved — emit tokens
    print("\n[Advisor] APPROVED. Token rows (JSON):\n")
    print(format_tokens(result, miner_plan))
    print("\nFactorySpawner command (paste in-game chat):\n")
    print(format_spawner_command(result))
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Satisfactory AI factory advisor — plans a production chain and waits for approval."
    )
    parser.add_argument("command", nargs="?", help='Build order, e.g. "screws at 120/min"')
    parser.add_argument("--recipes", metavar="PATH",
                        help="Path to normalized recipe JSON export")
    parser.add_argument("--frm-host", metavar="HOST",
                        help="FRM server host (enables siting)")
    parser.add_argument("--frm-port", type=int, default=8080, metavar="PORT",
                        help="FRM HTTP port (default 8080)")
    parser.add_argument("--alternate", metavar="CLASS", action="append", default=[],
                        help="Prefer this alternate recipe class (repeatable)")
    parser.add_argument("--miner-tier", type=int, default=3, choices=[1, 2, 3],
                        metavar="TIER",
                        help="Highest unlocked miner tier (1/2/3, default 3)")
    parser.add_argument("--yes", action="store_true",
                        help="Non-interactive: auto-approve and print tokens")
    args = parser.parse_args()

    command = args.command
    if not command:
        print("Interactive mode — enter a build order:")
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

    run_advisor(
        command=command,
        recipes_path=args.recipes,
        frm_host=args.frm_host,
        frm_port=args.frm_port,
        prefer_alternate=set(args.alternate),
        miner_tier=args.miner_tier,
        non_interactive=args.yes,
    )


if __name__ == "__main__":
    main()
