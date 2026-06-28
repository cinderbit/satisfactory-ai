# Step 5 — Forked FactorySpawner: HTTP Listener + Coordinate Placement + Miner Spawn

**Audience:** whoever implements the C++ mod work.
**Base:** `github.com/uniqueSimon/FactorySpawner` (MIT). Fork freely.
**Target:** Satisfactory 1.2 / SML 3.12 / UE 5.6.1 CSS fork.

---

## What changes vs. upstream

| Area | Upstream | Fork |
|---|---|---|
| Entry point | Chat command parser (`FactoryCommandParser.cpp`) | HTTP listener on port 8082 |
| Placement | From player location | From `origin` coordinates in request |
| Machines placed | Manufacturers only | Manufacturers + miners/extractors |
| Node validation | None | Reject nodes not in discovered set |
| Recipe/belt/power | Unchanged — reuse entirely | Unchanged |
| Blueprint write | Supported | Supported (opt-in via `writeBlueprint` flag) |

Everything in `BuildPlanGenerator.cpp` below `Generate()` is reused unchanged.

---

## 1. HTTP Listener

Add a new module: `FactoryHttpListener.cpp / .h`

**Port:** 8082 (hardcoded default; expose as a mod config option).
**Protocol:** HTTP/1.1, no TLS (local machine / LAN only).
**Endpoint:** `POST /build` — accepts JSON body, returns JSON response.
**Health check:** `GET /health` — returns `{"status":"ok"}` immediately.

### SML HTTP server

Use SML's built-in `FHttpServerModule` (available in UE 5.x via
`#include "HttpServerModule.h"`). Register the route in
`AFactorySpawnerSubsystem::BeginPlay()`:

```cpp
auto& HttpModule = FHttpServerModule::Get();
auto Router = HttpModule.GetHttpRouter(8082);

Router->BindRoute(
    FHttpPath(TEXT("/build")), EHttpServerRequestVerbs::VERB_POST,
    FHttpRequestHandler::CreateUObject(this, &AFactorySpawnerSubsystem::HandleBuild)
);
Router->BindRoute(
    FHttpPath(TEXT("/health")), EHttpServerRequestVerbs::VERB_GET,
    FHttpRequestHandler::CreateLambda([](const FHttpServerRequest&,
                                         const FHttpResultCallback& OnComplete) {
        OnComplete(FHttpServerResponse::Create(TEXT("{\"status\":\"ok\"}"),
                                               TEXT("application/json")));
        return true;
    })
);
HttpModule.StartAllListeners();
```

Shut down in `EndPlay()`:
```cpp
FHttpServerModule::Get().StopAllListeners();
```

---

## 2. Request / Response JSON schema

### POST /build — request body

```json
{
  "extractors": [
    {
      "machineType": "Miner",
      "minerTier":   3,
      "itemClass":   "Desc_OreIron_C",
      "clockSpeed":  75.0,
      "nodeX":       12400.0,
      "nodeY":       -8300.0,
      "nodeZ":       200.0
    },
    {
      "machineType": "WaterExtractor",
      "minerTier":   1,
      "itemClass":   "Desc_Water_C",
      "clockSpeed":  100.0,
      "nodeX":       5000.0,
      "nodeY":       3000.0,
      "nodeZ":       0.0
    }
  ],
  "manufacturers": [
    { "machineType": "Smelter",      "count": 3, "recipe": "IronIngot", "clockSpeed": 100.0 },
    { "machineType": "Constructor",  "count": 5, "recipe": "IronRod",   "clockSpeed": 100.0 },
    { "machineType": "Constructor",  "count": 8, "recipe": "Screw",     "clockSpeed": 100.0 }
  ],
  "originX": 12400.0,
  "originY": -8300.0,
  "originZ": 200.0,
  "writeBlueprint": false
}
```

### POST /build — success response

```json
{ "status": "ok", "message": "Spawned 16 machines, 3 extractors." }
```

### POST /build — error response

```json
{
  "status": "error",
  "message": "Validation failed",
  "errors": [
    "Node at X=99000 Y=44000 is not in the player's discovered set",
    "Recipe 'BadRecipeName' not found"
  ]
}
```

---

## 3. Node discovery validation

Before spawning anything, validate every extractor token:

```cpp
bool AFactorySpawnerSubsystem::IsNodeDiscovered(
    float NodeX, float NodeY, float NodeZ) const
{
    FVector NodeLoc(NodeX, NodeY, NodeZ);

    // Check 1: existing extractor within 1000 uu of this location
    for (TActorIterator<AFGBuildableResourceExtractor> It(GetWorld()); It; ++It)
    {
        if (FVector::Dist2D(It->GetActorLocation(), NodeLoc) < 1000.f)
            return true;
    }

    // Check 2: inside a radar tower's scan radius
    for (TActorIterator<AFGBuildableRadarTower> It(GetWorld()); It; ++It)
    {
        float Radius = It->GetScanRadius(); // UU — verify method name in CSS headers
        if (FVector::Dist2D(It->GetActorLocation(), NodeLoc) <= Radius)
            return true;
    }

    return false;
}
```

Reject the entire request (return error JSON, spawn nothing) if any node
fails this check. Do not partial-spawn.

---

## 4. Extractor spawn logic

Add `SpawnExtractor()` alongside the existing `SpawnManufacturer()`:

```cpp
AFGBuildableResourceExtractor* AFactorySpawnerSubsystem::SpawnExtractor(
    const FExtractorToken& Token)
{
    // 1. Find the resource node actor nearest to (Token.NodeX/Y/Z)
    AFGResourceNode* TargetNode = FindNearestResourceNode(
        FVector(Token.NodeX, Token.NodeY, Token.NodeZ), 1000.f);
    if (!TargetNode) return nullptr;

    // 2. Resolve extractor class from machineType + minerTier
    TSubclassOf<AFGBuildableResourceExtractor> ExtractorClass =
        GetExtractorClass(Token.MachineType, Token.MinerTier);
    if (!ExtractorClass) return nullptr;

    // 3. Compute spawn transform — align to node, keep Z up
    FTransform SpawnTransform = TargetNode->GetActorTransform();

    // 4. Spawn (same pattern as manufacturer spawn in upstream)
    AFGBuildableResourceExtractor* Extractor =
        GetWorld()->SpawnActor<AFGBuildableResourceExtractor>(
            ExtractorClass, SpawnTransform,
            FActorSpawnParameters());
    if (!Extractor) return nullptr;

    // 5. Connect to node
    Extractor->SetResourceNode(TargetNode);
    TargetNode->SetIsOccupied(true);

    // 6. Apply clock speed via RCO (multiplayer-safe, same as manufacturer path)
    if (Token.ClockSpeed != 100.f)
    {
        // Use RCO->Server_PasteSettings path — see upstream for manufacturer example
        ApplyClockSpeed(Extractor, Token.ClockSpeed / 100.f);
    }

    return Extractor;
}
```

### Extractor class map

```cpp
TSubclassOf<AFGBuildableResourceExtractor>
AFactorySpawnerSubsystem::GetExtractorClass(
    const FString& MachineType, int32 Tier)
{
    static const TMap<FString, TArray<FSoftClassPath>> ClassMap = {
        { "Miner", {
            FSoftClassPath(TEXT("/Game/FactoryGame/Buildable/Factory/"
                               "MinerMk1/Build_MinerMk1.Build_MinerMk1_C")),
            FSoftClassPath(TEXT("/Game/FactoryGame/Buildable/Factory/"
                               "MinerMk2/Build_MinerMk2.Build_MinerMk2_C")),
            FSoftClassPath(TEXT("/Game/FactoryGame/Buildable/Factory/"
                               "MinerMk3/Build_MinerMk3.Build_MinerMk3_C")),
        }},
        { "WaterExtractor", {
            FSoftClassPath(TEXT("/Game/FactoryGame/Buildable/Factory/"
                               "WaterPump/Build_WaterPump.Build_WaterPump_C")),
        }},
        { "ResourceExtractor", {
            FSoftClassPath(TEXT("/Game/FactoryGame/Buildable/Factory/"
                               "FrackingExtractor/Build_FrackingExtractor"
                               ".Build_FrackingExtractor_C")),
        }},
    };

    const TArray<FSoftClassPath>* Classes = ClassMap.Find(MachineType);
    if (!Classes) return nullptr;
    int32 Idx = FMath::Clamp(Tier - 1, 0, Classes->Num() - 1);
    return Cast<UClass>((*Classes)[Idx].TryLoad());
}
```

> **Verify these asset paths** against your CSS Unreal project. They are
> correct for Satisfactory 1.0/1.2 but CSS sometimes renames assets between
> updates. Search for `MinerMk3` in the content browser to confirm.

---

## 5. Coordinate-based manufacturer placement

Upstream's `Generate()` builds from the player's location. Replace the
cursor initialisation:

```cpp
// UPSTREAM (remove):
FVector XCursor = PlayerCharacter->GetActorLocation();

// FORK (replace with):
FVector XCursor = FVector(Request.OriginX, Request.OriginY, Request.OriginZ);
```

Everything else in `Generate()` — the row loop, belt routing, pipe routing,
power pole alternation — stays identical.

---

## 6. HandleBuild entry point

```cpp
bool AFactorySpawnerSubsystem::HandleBuild(
    const FHttpServerRequest& Request,
    const FHttpResultCallback& OnComplete)
{
    // 1. Parse JSON
    FBuildRequest BuildReq;
    if (!ParseBuildRequest(Request.Body, BuildReq))
    {
        OnComplete(ErrorResponse(TEXT("Invalid JSON")));
        return true;
    }

    // 2. Validate all nodes are discovered
    TArray<FString> ValidationErrors;
    for (const FExtractorToken& ET : BuildReq.Extractors)
    {
        if (!IsNodeDiscovered(ET.NodeX, ET.NodeY, ET.NodeZ))
        {
            ValidationErrors.Add(FString::Printf(
                TEXT("Node at X=%.0f Y=%.0f is not in the player's discovered set"),
                ET.NodeX, ET.NodeY));
        }
    }
    if (ValidationErrors.Num() > 0)
    {
        OnComplete(ErrorResponse(TEXT("Validation failed"), ValidationErrors));
        return true;
    }

    // 3. Must run on game thread
    AsyncTask(ENamedThreads::GameThread, [this, BuildReq, OnComplete]()
    {
        TArray<FString> Errors;
        int32 ExtractorCount = 0;

        // Spawn extractors first
        for (const FExtractorToken& ET : BuildReq.Extractors)
        {
            if (SpawnExtractor(ET))
                ExtractorCount++;
            else
                Errors.Add(FString::Printf(
                    TEXT("Failed to spawn %s at X=%.0f Y=%.0f"),
                    *ET.MachineType, ET.NodeX, ET.NodeY));
        }

        // Build manufacturer rows at origin
        int32 MachineCount = 0;
        if (Errors.Num() == 0)
        {
            // Convert manufacturer tokens to FFactoryCommandToken array
            // and call the existing Generate() entry point
            TArray<FFactoryCommandToken> Tokens =
                BuildManufacturerTokens(BuildReq.Manufacturers);
            MachineCount = Generate(Tokens,
                FVector(BuildReq.OriginX, BuildReq.OriginY, BuildReq.OriginZ),
                BuildReq.WriteBlueprint);
        }

        FString Msg = FString::Printf(
            TEXT("Spawned %d machines, %d extractors."),
            MachineCount, ExtractorCount);
        OnComplete(Errors.Num() == 0
            ? OkResponse(Msg)
            : ErrorResponse(TEXT("Partial failure"), Errors));
    });

    return true;
}
```

---

## 7. Generate() signature change

Upstream:
```cpp
void ABuildPlanGenerator::Generate(TArray<FFactoryCommandToken> Tokens);
```

Fork — add origin + blueprint flag:
```cpp
int32 ABuildPlanGenerator::Generate(
    TArray<FFactoryCommandToken> Tokens,
    FVector Origin,
    bool bWriteBlueprint);
```

Returns machine count spawned. `Origin` replaces the player-location cursor
init (see §5). `bWriteBlueprint` passes through to the existing
`AFGBlueprintSubsystem::WriteBlueprintToArchive(...)` call at the end.

---

## 8. Build order for the mod fork

1. Get toolchain green: SML hello-world compiles and loads (see VERIFY_FIRST.md §4).
2. Fork upstream; confirm it builds unmodified.
3. Add `GET /health` listener — simplest possible change, confirms HTTP works.
4. Add coordinate origin to `Generate()` — test with a manual POST.
5. Add extractor spawn (`SpawnExtractor`) — test on a known node.
6. Add node discovery validation — test rejection of an undiscovered node.
7. Wire `HandleBuild` end-to-end.
8. Test the full advisor → mod flow with a real recipe.

---

## 9. Things to verify against live headers/assets

- `AFGBuildableRadarTower::GetScanRadius()` — confirm method name in CSS headers
- `AFGResourceNode::SetIsOccupied()` — or equivalent to mark node as in-use
- `AFGBuildableResourceExtractor::SetResourceNode()` — confirm method name
- Asset paths for all three miner tiers + water pump + fracking extractor
- Whether `FHttpServerModule` is available in SML 3.12's UE build or if a
  custom HTTP library is needed (FRM uses its own; borrowing from FRM is fine)
