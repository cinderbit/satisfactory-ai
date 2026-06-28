# Recipe Parsing Reference

Companion to `spec.md` §5. Detailed guidance for the recipe-graph planner.

## Data source

Prefer a **normalized** recipe export over raw `Docs.json`.

- Raw file ships with the game at:
  `…/Satisfactory/CommunityResources/Docs/Docs.json`
- Cleaner option: run `SatisfactoryDocsExporter` against the install, or pull a
  pre-generated, version-matched export. The cleaned format resolves class-
  hierarchy and custom-encoding pain in the raw file.
- **Whatever the source: it must match the game build the server runs (1.2).**

## Recipe fields used

| Field | Meaning |
|---|---|
| `Ingredients[] {Item, Amount}` | inputs |
| `Products[] {Item, Amount}` | outputs |
| `ManufacturingDuration` | seconds per craft cycle |
| `ProducedIn[]` | machine(s) — map to the fixed machine enum |

## Rate formula

```
per_machine_per_min = product_amount / manufacturing_duration * 60
machines_needed     = ceil(target_rate_per_min / per_machine_per_min)
```
Apply **after** fluid normalization.

## Preprocessing rules (mandatory)

1. **Raw-resource leaves** (no recipe; stop traversal here):
   Iron Ore, Copper Ore, Limestone, Coal, Caterium Ore, Sulfur, Raw Quartz,
   Bauxite, Uranium, S.A.M. Ore, Crude Oil, Water.
2. **Fluid amounts are ×1000** in the data. Divide liquids by 1000 (or treat
   units consistently) before rate math.
3. **Alternate recipes:** the data flags alternates. Default to standard recipes
   unless the command specifies an alternate. Keep alternates available for the
   planner to offer.
4. **ProducedIn → enum:** map the producer string (e.g. `Build_ConstructorMk1`)
   to the machine enum used by the mod. Only 14 machine types matter.

## Worked example: Screws @ 120/min (standard recipes)

Chain: Screw ← Iron Rod ← Iron Ingot ← Iron Ore (leaf)

Standard recipe rates (verify against your export — illustrative):
- **Screw:** Constructor, 4 Iron Rod → 4 Screw, ~6s → check actual; screws are
  commonly 1 rod → 4 screws @ certain duration. USE THE EXPORT, don't trust memory.
- **Iron Rod:** Constructor, 1 Iron Ingot → 1 Iron Rod.
- **Iron Ingot:** Smelter, 1 Iron Ore → 1 Iron Ingot.

> NOTE: exact amounts/durations MUST come from the recipe export, not from this
> doc. The point of the example is the SHAPE of the output, below.

Planner output shape (the token rows handed to the mod):
```
[
  {count: N1, machineType: "Smelter",     recipe: "IronIngot"},
  {count: N2, machineType: "Constructor", recipe: "IronRod"},
  {count: N3, machineType: "Constructor", recipe: "Screw"},
]
```
Plus a BOM: `{ "Iron Ore": R_ore_per_min }` for the siting/material-gap step.

## Traversal notes

- Build a DAG keyed by item; edges weighted by required input rate.
- Multi-output recipes and byproducts exist (esp. refinery/blender) — handle
  products list length > 1; match the target product, track byproducts in BOM.
- Cycle guard: raw-resource leaves terminate; assert no cycles remain after
  leaf-pruning.
- Round machine counts up per stage; surface resulting overproduction in the
  plan so the human sees slack before approving.
