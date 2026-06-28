# VERIFY FIRST — Live-Environment Checklist

These items cannot be resolved from documentation alone. Clear them against the
ACTUAL running server/install before (or while) building the dependent component.
None are architectural risks — they are checks, not research.

---

## 1. Version alignment  [blocks: everything]

Confirm all of these target the SAME game build (1.2.x):

- [ ] Dedicated server build version (check server logs / `/api/v1` info)
- [ ] SML version installed (need 3.12+ for 1.2)
- [ ] Factory Spawner fork builds against the matching Unreal-CSS engine
      (UE 5.6.1 custom; cross-compile toolchain v25 clang-18.1.0 for Linux server)
- [ ] FRM mod version compatible with the same build
- [ ] Recipe export (`Docs.json` or cleaned) generated from the same build

Record the exact CL/build number here: ____________________

---

## 2. FRM JSON field mapping  [blocks: 4.3 world-state reader, 4.2 siting]

Hit the live FRM endpoint and the official `:7777/api/v1/` and record real shapes.

- [ ] FRM web server reachable (default port; `/frm http start` if needed)
- [ ] Endpoint that returns resource NODES — record its path: ____________
- [ ] Field name for node PURITY (impure/normal/pure): ____________
- [ ] Field names for node WORLD COORDINATES (x/y/z): ____________
- [ ] Endpoint for player/inventory/storage contents (material-gap step): ______
- [ ] Field shape for item counts in storage: ____________
- [ ] Official `:7777/api/v1/` — confirm which reads it provides vs. FRM, and
      whether HTTPS/cert handling is needed for the POST mode.

Paste a trimmed sample JSON for each into the reader's test fixtures.

---

## 3. Recipe export sanity  [blocks: 4.1 planner]

- [ ] Locate/generate the recipe export for build 1.2.x
- [ ] Confirm Screw, Iron Rod, Iron Ingot recipes parse with real
      amounts + durations (do NOT trust remembered values)
- [ ] Confirm fluid recipe (e.g. anything with Water) shows the ×1000 scaling
      so normalization is applied correctly
- [ ] Confirm `ProducedIn` strings map cleanly to the 14-machine enum
- [ ] Spot-check one alternate recipe is flagged as alternate

---

## 4. Mod build toolchain (gate for any C++)  [blocks: 4.5 fork]

Before touching the fork, get a clean SML hello-world compiling — the toolchain
is half the battle.

- [ ] Custom Unreal Engine (CSS fork) installed + opens
- [ ] Wwise integrated (required even if unused)
- [ ] Alpakit packages the Example Mod
- [ ] Linux dedicated-server cross-compile works (your server is Linux/k3s)
- [ ] THEN: fork Factory Spawner, confirm upstream builds unmodified before
      swapping the parser for HTTP

---

## 5. Design decision to lock  [blocks: 4.5 fork behavior]

- [ ] Blueprint-write (player stamps manually) vs. direct placement (hands-off)?
      Upstream = blueprint-write. Direct placement = one-function divergence.
      Decision: ____________________

---

## Suggested order

1. Item 3 (recipe export) — unblocks the planner, your first build, no game online.
2. Item 2 (FRM fields) — needs server up; unblocks reader + siting.
3. Build the advisor (spec §6 steps 1–4). Ship it.
4. Item 1 + Item 4 (versions + toolchain) — gate the fork.
5. Item 5 decision, then build the fork (spec §6 step 5).
