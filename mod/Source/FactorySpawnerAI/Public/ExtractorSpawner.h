// ExtractorSpawner.h
//
// Spawns miners / extractors on resource nodes and applies clock speed via
// the RCO path (multiplayer/dedicated-server safe). New code in the fork —
// upstream FactorySpawner only spawns manufacturers.
//
// Part of the FactorySpawnerAI fork (MIT, see mod/LICENSE).

#pragma once

#include "CoreMinimal.h"
#include "BuildRequestTypes.h"

class UWorld;
class AFGBuildableResourceExtractor;
class AFGResourceNode;

namespace ExtractorSpawner
{
	/**
	 * Resolve the extractor buildable class for a (machineType, tier) pair.
	 * Returns nullptr if the type is unknown or the class fails to load.
	 */
	TSubclassOf<AFGBuildableResourceExtractor> GetExtractorClass(
		const FString& MachineType, int32 Tier);

	/**
	 * Find the resource node nearest to (X,Y,Z) within SearchRadius (2D, uu).
	 * Returns nullptr if none is close enough.
	 */
	AFGResourceNode* FindNearestResourceNode(
		UWorld* World, float X, float Y, float Z, float SearchRadius);

	/**
	 * Spawn one extractor described by Token and connect it to its node.
	 * Applies clock speed if != 100. Returns nullptr on any failure and
	 * writes a reason into OutError.
	 */
	AFGBuildableResourceExtractor* SpawnExtractor(
		UWorld* World, const FExtractorToken& Token, FString& OutError);
}
