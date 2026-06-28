# AI Factory Builder for Satisfactory — Build Spec

**Audience:** Claude Code (implementation). This document is the authoritative spec.
**Status:** Planning complete. Architecture validated against existing open-source mod.
**Author of plan:** (handoff from planning session)

---

## 1. Goal

A command-driven agent that accepts a natural-language build order — e.g.
*"build a screws factory at 120/min"* — and:

1. Plans the full production chain (machines, counts, recipes, rates).
2. Searches the world for resource nodes and computes a build location.
3. Computes the material gap (what's needed vs. what the player has).
4. Presents the plan and **waits for human approval**.
5. On approval, generates the factory **live on a dedicated server** as a
   native blueprint, via a forked Factory Spawner mod driven over HTTP.

The agent takes commands and acts on them. It does NOT act autonomously without
approval. It does NOT "wander off."

---

## 2. Architecture

```
You (NL command)
      │
      ▼
┌─────────────────────────┐     reads      ┌──────────────────────┐
│  Python Agent           │ ◄────────────► │  FRM JSON API        │
│  - NL parse             │   world state  │  + official :7777 API│
│  - recipe-graph planner │                └──────────────────────┘
│  - siting optimizer     │
│  - approval gate        │
└───────────┬─────────────┘
            │ token rows (HTTP POST)
            ▼
┌─────────────────────────┐
│  Forked Factory Spawner │  (C++ / SML mod, MIT-licensed base)
│  - HTTP listener        │  ← replaces the chat-command parser
│  - spawn + connect      │  ← REUSED unchanged from upstream
│  - blueprint write      │  ← REUSED unchanged from upstream
└───────────┬─────────────┘
            ▼
   Native blueprint in-game → player stamps it (or auto-place; see §7 decision)
```

### The critical seam
The entire system pivots on ONE contract: the Python agent emits a list of
**command tokens**, each `{count, machineType, recipe, clock}`. The mod consumes
that list. Everything downstream of the token list is reusable code from Factory
Spawner. Everything upstream is the Python brain. Keep this boundary clean.

Token struct (from upstream `BuildPlanTypes.h`):
```
count:       int    (positive)
machineType: enum   (Smelter|Constructor|Assembler|Foundry|Manufacturer|
                      OilRefinery|Blender|Converter|ParticleAccelerator|
                      QuantumEncoder|Packager|CoalGenerator|FuelGenerator|
                      NuclearReactor)
recipe:      string (optional, e.g. "IronIngot" or "IngotIron" — both accepted)
clock:       float  (optional, 0–100 percent; uses RCO path when set)
beltTier:    int    (optional, 1–6; else auto-detect highest unlocked)
```

---

## 3. Upstream base: Factory Spawner (study + fork this)

- **Repo:** `github.com/uniqueSimon/FactorySpawner`
- **License:** MIT (Copyright (c) 2025 Simon Steinhauser). Full reuse permitted;
  retain the notice. Fork freely.
- **What it already solves (reuse, do not rebuild):**
  - Direct actor spawn: `World->SpawnActor<AFGBuildableManufacturer>(class, transform)`
    — NO hologram/build-gun driving needed.
  - Recipe set: `Man->SetRecipe(RecipeClass)`; clocked path uses
    `RCO->Server_PasteSettings(...)` (multiplayer/dedicated-server safe).
  - Belt connect: `UFGTestBlueprintFunctionLibrary::SpawnSplineBuildable(BeltClass,
    From, To)` + `Respline(...)`.
  - Belt-vs-lift auto choice by distance heuristic.
  - Pipe connect via pipe-cross; power via auto pole+wire alternation.
  - Blueprint write: `AFGBlueprintSubsystem::WriteBlueprintToArchive(...)`, then
    destroys the source buildables so the artifact is a clean native blueprint.
  - Per-machine footprint + connection-port geometry: `MachineConfigList`
    (already extracted to Python — see `factory_geometry.py`).
- **What you replace:** `FactoryCommandParser.cpp` → an HTTP listener that
  receives token rows from the Python agent. The generator (`BuildPlanGenerator`)
  stays. Its `Generate(TArray<FFactoryCommandToken>)` entry point is your target.

---

## 4. Components to build

### 4.1 Recipe-graph planner (pure Python, no game dependency)
- **Input:** target item + rate (e.g. Screw @ 120/min).
- **Data source:** a *normalized* recipe export, NOT raw `Docs.json` (see §5).
- **Logic:** build a dependency DAG; traverse from target to raw leaves; at each
  stage compute machines needed = ceil(target_rate / per_machine_rate), where
  per_machine_rate = product_amount / manufacturing_duration * 60.
- **Output:** the token rows + a bill of materials (raw inputs/min).
- This is the intellectual core and is fully parallelizable from all game work.

### 4.2 Geometry / siting layer (Python)
- **Foundation built:** `factory_geometry.py` — footprints, ports, variant logic,
  `row_footprint()`. Verified against upstream numbers.
- **To add:** node-search siting. Consume FRM world state, score candidate sites
  by node purity + distance to demand, reserve footprint via `row_footprint()`.
- **Tiling rule (resolved):** reserve each module's footprint plus ~8–10m belt
  aisle between tiled blueprints. Derived from the mod's own row spacing
  (input/output `length` fields already include routing space). Blueprints snap
  center-to-center in Blueprint mode.

### 4.3 World-state reader (Python)
- FRM JSON over HTTP (FRM is server-only; friends need not install it).
- Official dedicated-server API at `https://<ServerIP>:7777/api/v1/` for reads.
- **Verify-first:** map FRM's actual field names for node purity + coordinates
  against a live endpoint before building this (see checklist).

### 4.4 Approval gate (Python)
- Present plan (machines, counts, site, material gaps). Wait for yes/no/modify.
- CLI to start; optional small web UI on the Beelink later.

### 4.5 Forked mod (C++ — the only Unreal work)
- Fork Factory Spawner. Add HTTP listener. Feed received tokens straight into
  `BuildPlanGenerator::Generate`. Keep all spawn/connect/blueprint code.

---

## 5. Recipe data: gotchas (bake these into the parser)

The planner targets a **normalized** recipe JSON. Raw `Docs.json` works but is
painful; prefer a cleaned, version-matched export (e.g. SatisfactoryDocsExporter
output, or a pre-generated file matching your game build).

Mandatory preprocessing rules:

1. **Raw resources are not recipes.** Docs.json has no flag marking minable ores.
   Hardcode these as leaf nodes or graph traversal won't terminate:
   Iron Ore, Copper Ore, Limestone, Coal, Caterium Ore, Sulfur, Raw Quartz,
   Bauxite, Uranium, S.A.M. Ore (miners); Crude Oil (oil extractor); Water
   (water extractor).
2. **Fluids are ×1000.** Liquid amounts in recipes are scaled by 1000
   (e.g. "Water Amount 4800" = 4.8 m³). Normalize before rate math or liquid
   stages are off by 1000×.
3. **Class-link gaps.** `mBuildableClass` is missing from build descriptors;
   linking a recipe's `ProducedIn` to a concrete machine may need a small manual
   map. For THIS project the machine enum is already fixed (14 types), so map
   `ProducedIn` strings → the enum directly.
4. **Recipe rate formula:** `per_machine_per_min = product_amount /
   manufacturing_duration * 60`, applied AFTER fluid normalization.

Relevant schema fields: `Ingredients[] {Item, Amount}`, `Products[] {Item,
Amount}`, `ManufacturingDuration`, `ProducedIn[]`.

---

## 6. Build order (hardest C++ last — deliberate de-risking)

1. **Recipe-graph planner** → emits valid token rows + BOM. Pure Python.
2. **World-state reader** → FRM JSON into Python. (Verify fields first.)
3. **Siting optimizer** → picks location, computes material gap.
4. **Approval loop** → end-to-end ADVISOR that prints a manual
   `/FactorySpawner ...` command for the player to paste.
   **← Fully working product, ZERO new C++.** Ship this first.
5. **Fork the mod** → swap chat parser for HTTP bridge → automate the stamp.
   The only real Unreal work, fully isolated, added last.

Each step is independently useful. Step 4 is a genuine milestone you can use.

---

## 7. Decisions still owned by the human (resolve before/while building)

1. **Game-version alignment.** Dedicated server + SML (3.12+) + Factory Spawner
   fork + FRM + the recipe export must all target the same build (1.2). VERIFY.
2. **FRM JSON shapes.** Probe the live endpoint; map purity + coordinate fields
   before coding 4.3.
3. **Blueprint vs. direct placement.** Upstream writes a blueprint then destroys
   originals (player stamps manually). For a fully hands-off agent you may prefer
   direct placement (skip the manual stamp). One-function divergence in the fork.
   Decide based on how "automatic" you want the final action to feel.

---

## 8. Constraints / facts to respect

- Blueprint Designer bounding box: 32m³ vanilla; Blueprint Designer+ (KMods,
  Tier-6 MAM research) enlarges it. Large factories tile across multiple
  blueprints; they snap center-to-center.
- Port-variant selection depends on the recipe's solid (belt) vs. liquid (pipe)
  split. Planner and geometry are coupled here — see `port_variant_index()` in
  `factory_geometry.py`. Variant 0 = max belts + max pipes = safe default before
  recipe is known.
- Clocked machines MUST use the RCO path (`Server_PasteSettings`) for multiplayer
  correctness — upstream already does this.
- 1 grid unit = 1 meter = 100 Unreal units. Geometry module handles the scaling.

---

## 9. Files in this bundle

- `spec.md` — this document.
- `factory_geometry.py` — machine footprints, ports, variant logic, footprint
  helper. Runnable demo in `__main__`. Verified against upstream.
- `recipe_parsing_notes.md` — detailed parser reference with the §5 gotchas and
  the rate formula, plus the screws-chain worked example.
- `VERIFY_FIRST.md` — the live-environment checklist (the §7 items) to clear
  against the actual server before/while building.
