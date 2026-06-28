# Windows Modding Toolchain Setup

Ordered checklist to get from a clean Windows machine to a compiling
FactorySpawnerAI mod. Clears `VERIFY_FIRST.md` §4.

> **Authoritative source:** https://docs.ficsit.app/ — the Satisfactory Modding
> docs. Exact versions (UE build, Wwise, clang) change between game releases;
> when this doc and ficsit.app disagree, ficsit.app wins. Targets game **1.2**.

## Division of labor

Some steps are interactive and only you can do them (account linking, large
downloads, license clicks). Once the toolchain is in place, Claude Code drives
the build/iterate loop. Marked below as **[you]** vs **[claude]**.

---

## 0. Get Claude Code onto this machine  [you]

```bash
# Install Claude Code CLI: https://claude.ai/code
git clone https://github.com/cinderbit/satisfactory-ai
cd satisfactory-ai
git checkout claude/satisfactory-ai-bot-spoc7j
claude
```

From here on, Claude works in this directory with access to your real
filesystem, game install, and toolchain.

## 1. Base dev tools  [you]

- **Visual Studio 2022** (Community is fine) with workloads:
  - "Game development with C++"
  - "Desktop development with C++"
  - ".NET desktop development"
  - Individual components: "Unreal Engine installer", latest Windows 10/11 SDK,
    MSVC v143 toolset
- **.NET SDK** (current LTS)
- **Git** (you have it if you cloned this)
- Confirm exact required VS components on ficsit.app — they pin specifics.

## 2. Epic + GitHub link (for the UE source)  [you]

The Satisfactory UE is a **private Coffee Stain fork** of Unreal Engine. To
clone it you must:

1. Link your Epic Games account to GitHub:
   https://www.unrealengine.com/en-US/ue-on-github
2. Accept the invite to the EpicGames org.
3. Get access to the CSS / Satisfactory Modding UE fork repo — request via the
   [Satisfactory Modding Discord](https://discord.gg/xkVJ73E) per ficsit.app.

## 3. Wwise  [you]

- Install the **Audiokinetic Launcher**, then the Wwise version ficsit.app
  specifies for 1.2.
- Required even though this mod uses no audio — the engine won't build without
  it.

## 4. Starter project + engine build  [you, with claude]

- Clone the **SatisfactoryModLoader** starter project (per ficsit.app).
- This pulls the custom UE fork (large — 100GB+ built; allow disk + hours).
- Generate project files, open in VS, build the **Development Editor** target.
- **[claude]** can run the generate/build commands and triage compile errors
  once the sources are present.

## 5. Verify the toolchain on the Example Mod  [claude]

Before touching our code, confirm the pipeline end-to-end:

- Package the bundled **Example Mod** with **Alpakit**.
- Install it via Satisfactory Mod Manager, launch the game, confirm it loads.
- If this works, the toolchain is green. If not, fix here — not against our mod.

## 6. Fork FactorySpawner, confirm it builds unmodified  [claude]

- Fork `github.com/uniqueSimon/FactorySpawner`.
- Drop it into the starter project's `Mods/` (or `Plugins/`) tree.
- Build + Alpakit it **unchanged**. Confirm it loads in-game.
- This isolates "toolchain works" from "our changes work."

## 7. Merge FactorySpawnerAI  [claude]

- Copy `mod/Source/FactorySpawnerAI/` from this repo into the fork.
- Apply the two upstream patches in `docs/step5_cpp_spec.md` §5,§7:
  - `ABuildPlanGenerator::Generate()` gains `FVector Origin` + `bool
    bWriteBlueprint`, returns machine count.
  - Disable the chat-command registration (HTTP listener replaces it).
- Verify the CSS header/asset names flagged in `mod/README.md`.
- Build, Alpakit, install.

## 8. Linux dedicated-server cross-compile  [claude]
(only if you deploy to the Linux/k3s server rather than play locally)

- Install the UE Linux cross-compile toolchain (the `-v25 clang-18.1.0` build
  noted in `VERIFY_FIRST.md` §1 — confirm current version on ficsit.app).
- Alpakit the **server** target; deploy the mod to the dedicated server.

## 9. End-to-end test  [claude]

- Start the game (or server) with FactorySpawnerAI loaded.
- Confirm `GET http://localhost:8082/health` returns `{"status":"ok"}`.
- Run the advisor against live FRM:
  ```
  python advisor.py --recipes recipes.json --frm-host localhost \
                    --mod-host localhost "screws at 120/min"
  ```
- Approve; confirm the factory spawns at the sited coordinates and extractors
  land on discovered nodes only.

---

## What to hand Claude when you're set up

When you start Claude Code locally, tell it where things are so it can drive:

- Path to the SatisfactoryModLoader starter project
- Path to your Satisfactory install (for `Docs.json` + launching)
- FRM host/port (probably `localhost:8080`)
- Whether you're testing in single-player or against the dedicated server
