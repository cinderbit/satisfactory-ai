# Running a Local Session on Windows

How to move from this cloud session to one running on your Windows machine, and
confirm the advisor can read your live game world.

## Why this is needed

The cloud session (where this repo was built) runs in an isolated Linux
container with **no access to your Windows files, game install, or saves**.
A session running *on your Windows machine* does. The git repo carries the work
across; filesystem access does not.

> Note: the advisor never reads the `.sav` save file (it's a binary blob). Live
> world data comes from **FRM's HTTP API** while the game is running.

## 1. Start Claude Code locally

On the Windows machine:

```powershell
# In a terminal (PowerShell), clone and enter the repo
git clone https://github.com/cinderbit/satisfactory-ai
cd satisfactory-ai
git checkout claude/satisfactory-ai-bot-spoc7j

# Start Claude Code here (or open this folder in the Claude Code app)
claude
```

This session now has access to your local filesystem.

## 2. Install Python (if needed)

The advisor needs Python 3.10+. Check:

```powershell
python --version
```

No third-party packages are required (stdlib only).

## 3. Install the mods

Via [Satisfactory Mod Manager](https://smm.ficsit.app):

- **FRM (Ficsit Remote Monitoring)** — required for live world data.
- **FactorySpawnerAI** (our fork) — only needed later for Step 5 placement.

## 4. Launch the game and start FRM

1. Launch Satisfactory (single-player is fine), load your save.
2. FRM's web server starts automatically on port **8080** by default.
   If it isn't running, open the in-game chat and run:
   ```
   /frm http start
   ```

## 5. Confirm FRM is reachable and field-correct

Run the probe — it checks the live FRM JSON against what `world_state.py`
expects (clears VERIFY_FIRST.md §2 in one command):

```powershell
python tools\check_frm.py localhost 8080
```

Expected: `RESULT: FRM looks usable ✓`

If you see warnings about empty coords or item classes, FRM's field names
differ in your version — note the "actual keys" it prints and we adjust the
parsing in `world_state.py` (a small change).

## 6. Get a real recipe export

Replace the test fixture with a real export from your 1.2 install so recipe
rates are accurate (VERIFY_FIRST.md §3):

- Source: `<GameInstall>\CommunityResources\Docs\Docs.json`
- Normalize it (see `docs/recipe_parsing_notes.md`) and save as `recipes.json`.

## 7. Run the advisor against your real world

```powershell
python advisor.py --recipes recipes.json --frm-host localhost "screws at 120/min"
```

You'll get the full plan — machines, site, miner clocks, material gap — built
from *your* actual nodes and unlocked tiers, then the approval prompt.

Until the FactorySpawnerAI mod is built (Step 5), approving prints the token
rows and a `/FactorySpawner` paste command. Once the mod is running, add
`--mod-host localhost` and approval places the factory directly.

## What to hand the local Claude session

When you start Claude Code locally, tell it:

- Path to your Satisfactory install (for `Docs.json`)
- That FRM is running (`localhost:8080`)
- Whether you're testing single-player or against the dedicated server

Then we can verify fields, generate a real recipe export, and run the advisor
against your live game.
