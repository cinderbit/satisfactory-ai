# FactorySpawnerAI (mod fork)

A fork of [FactorySpawner](https://github.com/uniqueSimon/FactorySpawner)
(Simon Steinhauser, MIT) that replaces the in-game chat-command parser with an
**HTTP listener**, so the [satisfactory-ai](../README.md) Python advisor can
drive factory placement directly.

> **Status: source-complete, UNTESTED.** This C++ has not been compiled — it
> requires the Satisfactory modding toolchain (CSS Unreal Engine fork, Wwise,
> Alpakit) which can't run in CI. See `../docs/VERIFY_FIRST.md` §4 and the
> integration notes below before building.

## What this fork changes vs. upstream

| Area | Upstream | This fork |
|---|---|---|
| Command intake | Chat parser | HTTP listener on port 8082 |
| Placement origin | Player location | `origin` coords from the request |
| Machines | Manufacturers only | Manufacturers **+ miners/extractors** |
| Node safety | none | rejects nodes not in the discovered set |
| Recipe/belt/pipe/power | — | **reused unchanged** |

The design spec for all of this is `../docs/step5_cpp_spec.md`.

## New source files

```
Source/FactorySpawnerAI/
  FactorySpawnerAI.Build.cs           build rules (+HTTPServer, +Json)
  Public/
    BuildRequestTypes.h               USTRUCTs mirroring the POST /build JSON
    NodeDiscovery.h                   discovered-node validation
    ExtractorSpawner.h                miner/extractor spawn + node lookup
    FactorySpawnerAISubsystem.h       owns the HTTP listener; bridges to Generate()
  Private/
    NodeDiscovery.cpp
    ExtractorSpawner.cpp
    FactorySpawnerAISubsystem.cpp
    FactorySpawnerAIModule.cpp        module bootstrap
FactorySpawnerAI.uplugin              plugin descriptor
```

## How to actually build it

This `mod/` directory is the **new + changed** source only. To produce a
loadable mod you merge it into a real FactorySpawner fork inside a CSS Unreal
project:

1. Stand up the toolchain (CSS UE fork opens, Wwise integrated, Alpakit
   packages the Example Mod, Linux server cross-compile works).
   See `../docs/VERIFY_FIRST.md` §4.
2. Fork `uniqueSimon/FactorySpawner`; confirm it builds **unmodified** first.
3. Copy these files into the fork's plugin source tree. Where they reference
   upstream symbols (`ABuildPlanGenerator`, `FFactoryCommandToken`), keep the
   upstream definitions — only the call sites changed.
4. Apply the upstream integration patches (next section).
5. `alpakit` the plugin; install via Satisfactory Mod Manager.

## Required upstream integration patches

Two upstream changes this fork depends on (both in `docs/step5_cpp_spec.md`):

1. **`ABuildPlanGenerator::Generate()` signature** — add an `FVector Origin`
   and `bool bWriteBlueprint`, return the spawned machine count. Replace the
   cursor's player-location init with `Origin`. Everything else in `Generate()`
   stays identical.

2. **Remove/disable the chat-command registration** in
   `FactoryCommandParser.cpp` — the HTTP listener replaces it. (You can keep
   the chat path as a fallback if you want both.)

## Things to verify against live CSS headers

These accessor/asset names are correct for stock 1.x but CSS occasionally
renames them — confirm before relying on them:

- `AFGBuildableRadarTower::GetRevealRadius()` (vs `GetScanRadius()`)
- `AFGResourceNode::SetIsOccupied()` / `IsOccupied()`
- `AFGBuildableResourceExtractor::SetResourceNode()`
- `AFGBuildableResourceExtractor::SetPendingPotential()` and the RCO
  `Server_PasteSettings` path for dedicated-server-safe overclocking
- The miner/water-pump/fracking asset paths in `ExtractorSpawner.cpp`
- That SML 3.12's UE build exposes `FHttpServerModule` (FRM ships its own HTTP
  server — borrow from FRM if not)
