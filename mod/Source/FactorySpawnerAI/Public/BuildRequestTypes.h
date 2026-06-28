// BuildRequestTypes.h
//
// USTRUCT mirrors of the JSON payload POSTed by the Python advisor's
// mod_interface.py. These map 1:1 to the schema in docs/step5_cpp_spec.md §2
// so FJsonObjectConverter can deserialize the request body directly.
//
// Part of the FactorySpawnerAI fork (MIT, see mod/LICENSE).

#pragma once

#include "CoreMinimal.h"
#include "BuildRequestTypes.generated.h"

/** One miner/extractor to place on a specific resource node. */
USTRUCT()
struct FExtractorToken
{
	GENERATED_BODY()

	/** "Miner" | "WaterExtractor" | "ResourceExtractor" */
	UPROPERTY()
	FString machineType;

	/** 1/2/3 — clamped to available tiers per machine type */
	UPROPERTY()
	int32 minerTier = 1;

	/** e.g. "Desc_OreIron_C" */
	UPROPERTY()
	FString itemClass;

	/** 1.0–250.0 (percent) */
	UPROPERTY()
	float clockSpeed = 100.f;

	/** World coordinates of the target resource node (Unreal units). */
	UPROPERTY()
	float nodeX = 0.f;

	UPROPERTY()
	float nodeY = 0.f;

	UPROPERTY()
	float nodeZ = 0.f;
};

/** A row of one machine type running a given recipe. */
USTRUCT()
struct FManufacturerToken
{
	GENERATED_BODY()

	/** e.g. "Smelter", "Constructor" */
	UPROPERTY()
	FString machineType;

	UPROPERTY()
	int32 count = 0;

	/** Display name or class name — the generator accepts both. */
	UPROPERTY()
	FString recipe;

	UPROPERTY()
	float clockSpeed = 100.f;
};

/** Full payload for POST /build. */
USTRUCT()
struct FBuildRequest
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FExtractorToken> extractors;

	UPROPERTY()
	TArray<FManufacturerToken> manufacturers;

	/** Top-left corner of the manufacturer block (Unreal units). */
	UPROPERTY()
	float originX = 0.f;

	UPROPERTY()
	float originY = 0.f;

	UPROPERTY()
	float originZ = 0.f;

	/** If true, write a Blueprint and destroy sources; else place directly. */
	UPROPERTY()
	bool writeBlueprint = false;
};
