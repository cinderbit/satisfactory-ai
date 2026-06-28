# satisfactory-ai

An AI factory advisor for Satisfactory. You tell it what you want to build and
how much of it you need. It works out the full production chain — every machine,
every recipe, every miner — clocks each extractor to hit the exact rate from your
available nodes, picks the best build site, and shows you the complete plan before
doing anything. You approve it, it stamps the factory.

The goal is to remove the spreadsheet from factory planning without removing the
player from the decision. You stay in control; the AI does the math.

---

## Why this exists

Satisfactory factory planning is genuinely complex: dependency chains across
dozens of items, node purity math, machine counts, overclock calculations,
belt throughput, physical layout. Most players either use external tools
(satisfactory-calculator.com, Ficsit.ing) or do it by hand. Neither option is
in-game or tied to your actual world state — they don't know which nodes you
have, what you've unlocked, or where you've already built.

This project connects those dots: your live world state (via
[FRM](https://github.com/porisius/FicsitRemoteMonitoring)) feeds a Python
planner that knows your nodes, your unlocked machines, and your recipes, then
drives [FactorySpawner](https://github.com/uniqueSimon/FactorySpawner) to
physically place the result in-game.

---

## Does it need a dedicated server?

**No.** It works on a local single-player save just as well as a dedicated server.

- **SML + mods** work in single-player — almost all Satisfactory mods do.
- **FRM** runs an HTTP server inside the game process regardless of game mode.
  Many single-player players already use it for factory dashboards.
- **FactorySpawner** uses SML hooks and `World->SpawnActor` — nothing
  dedicated-server-only.
- The only thing you lose on a local save is the official `:7777/api/v1/`
  dedicated-server API, which we only used for health checks. FRM covers
  everything the planner actually needs.

If you run a dedicated server, it works there too — just point `--frm-host` at
the server's IP instead of `localhost`.

---

## How it works

```
You: "build screws at 120/min"
        │
        ▼
  advisor.py  ── parses the order
        │         runs the recipe DAG
        │         queries FRM for your nodes + unlocked machines
        │         scores candidate build sites
        │         calculates miner/extractor clock speeds
        │
        ▼
  [Plan printed — machines, counts, site, miner clocks, material gap]
        │
   You: approve / reject / modify
        │
        ▼
  Token rows emitted → FactorySpawner stamps the factory in-game
```

The planner never acts without your sign-off. It shows overproduction slack,
material gaps, and the exact clock % for every extractor before you commit.

---

## Setup

### 1. Python (the advisor)

Python 3.10 or later. No third-party packages required.

```bash
git clone https://github.com/cinderbit/satisfactory-ai
cd satisfactory-ai
python advisor.py --help
```

### 2. Recipe export

The planner needs a recipe JSON from your game install. The cleanest way is to
use [SatisfactoryDocsExporter](https://github.com/greeny/SatisfactoryDocsParser)
against your local `Docs.json`:

```
<GameInstall>/CommunityResources/Docs/Docs.json
```

Export it to a normalized JSON and pass it as `--recipes recipes.json`.
The file must match your game version (1.2). See `docs/recipe_parsing_notes.md`
for the expected schema and gotchas (fluid ×1000 scaling, alternate recipe flags,
raw-resource leaves).

### 3. Mods (for live world data + factory placement)

Install via [Satisfactory Mod Manager](https://smm.ficsit.app) — works for both
local saves and dedicated servers.

| Mod | Purpose | Required for |
|---|---|---|
| **SML** (Satisfactory Mod Loader) | Mod runtime | Everything below |
| **[FRM](https://ficsit.app/mod/FicsitRemoteMonitoring)** | HTTP API for world state | Node data, miner tier detection, siting |
| **[FactorySpawner](https://ficsit.app/mod/FactorySpawner)** (fork) | Spawns the factory in-game | Step 5 (physical placement) |

FRM starts an HTTP server on port 8080 by default. Run `/frm http start` in the
game chat if it isn't running. For a local save, `--frm-host localhost` is all
you need.

> **Note:** FactorySpawner requires a fork that replaces its chat-command parser
> with an HTTP listener. That's step 5 of the build order (see below). Until
> then, the advisor prints a `/FactorySpawner` chat command you can paste manually.

### 4. Run it

```bash
# Plan-only (no FRM — prints plan, outputs manual paste command)
python advisor.py --recipes recipes.json "screws at 120/min"

# Full plan with live world data (FRM running locally)
python advisor.py --recipes recipes.json --frm-host localhost "screws at 120/min"

# Full plan against a dedicated server
python advisor.py --recipes recipes.json --frm-host 192.168.1.10 "iron rods at 60/min"

# Override miner tier (default: auto-detected from your placed buildings)
python advisor.py --recipes recipes.json --frm-host localhost --miner-tier 2 "coal at 240/min"

# Non-interactive / scripting
python advisor.py --recipes recipes.json --yes "screws at 120/min"
```

---

## Files

| File | Purpose |
|---|---|
| `advisor.py` | Main CLI — parses order, runs plan, approval gate |
| `recipe_planner.py` | DAG planner: computes token rows + bill of materials |
| `miner_planner.py` | Assigns nodes to BOM, calculates exact clock speeds |
| `factory_geometry.py` | Machine footprints + belt/pipe port geometry |
| `world_state.py` | FRM client: nodes, buildings, inventory |
| `siting.py` | Scores candidate build sites by node purity + coverage |
| `docs/spec.md` | Full architecture spec |
| `docs/recipe_parsing_notes.md` | Recipe parser reference and gotchas |
| `docs/VERIFY_FIRST.md` | Live-environment checklist |

---

## Build order

- [x] **Step 1** — Recipe-graph planner (`recipe_planner.py`)
- [x] **Step 2** — World-state reader (`world_state.py`)
- [x] **Step 3** — Siting optimizer (`siting.py`)
- [x] **Step 4** — Miner planner + approval loop CLI — **usable today** (paste command)
- [ ] **Step 5** — Fork FactorySpawner; add HTTP bridge for direct in-game placement

Steps 1–4 are fully working with zero C++. Step 5 is the only Unreal/C++ work
and is the last thing added — everything before it is independently useful.