# satisfactory-ai

Command-driven factory advisor for Satisfactory (dedicated server, 1.2).

Plans a full production chain from a natural-language build order, finds a
build site near the right resource nodes, surfaces the material gap, and waits
for human approval before emitting the token rows that drive the
[FactorySpawner](https://github.com/uniqueSimon/FactorySpawner) mod.

See `docs/spec.md` for the full architecture.

---

## Quick start

```bash
# No third-party dependencies — Python 3.10+ only
python advisor.py --recipes recipes.json "screws at 120/min"

# With FRM for automatic siting (needs FRM mod running on the server)
python advisor.py --recipes recipes.json \
                  --frm-host 192.168.1.10 \
                  "iron rods at 60/min"

# Non-interactive (CI / scripting)
python advisor.py --recipes recipes.json --yes "screws at 120/min"
```

## Providing a recipe export

The planner needs a normalized recipe JSON from your game install.
See `docs/recipe_parsing_notes.md` and `docs/VERIFY_FIRST.md` §3 for
how to generate one.  The expected schema per entry:

```json
{
  "ClassName":             "Recipe_IronIngot_C",
  "DisplayName":           "Iron Ingot",
  "Ingredients":           [{"Item": "Desc_OreIron_C", "Amount": 1}],
  "Products":              [{"Item": "Desc_IronIngot_C", "Amount": 1}],
  "ManufacturingDuration": 2.0,
  "ProducedIn":            ["Build_SmelterMk1_C"],
  "IsAlternate":           false
}
```

## Files

| File | Purpose |
|---|---|
| `advisor.py` | Main CLI — approval-gate advisor |
| `recipe_planner.py` | DAG planner: token rows + BOM |
| `factory_geometry.py` | Machine footprints + port geometry |
| `world_state.py` | FRM + official dedicated-server API client |
| `siting.py` | Node search + site scoring |
| `docs/spec.md` | Full architecture spec |
| `docs/recipe_parsing_notes.md` | Recipe parser reference |
| `docs/VERIFY_FIRST.md` | Live-environment checklist |

## Build order (spec §6)

- [x] **Step 1** — Recipe-graph planner (`recipe_planner.py`)
- [x] **Step 2** — World-state reader (`world_state.py`)
- [x] **Step 3** — Siting optimizer (`siting.py`)
- [x] **Step 4** — Approval loop CLI (`advisor.py`) ← ship this first
- [ ] **Step 5** — Fork the FactorySpawner mod; add HTTP bridge (C++ only)