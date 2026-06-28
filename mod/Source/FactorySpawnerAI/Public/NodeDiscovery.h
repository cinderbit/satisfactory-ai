// NodeDiscovery.h
//
// Server-side validation that a resource node is in the player's discovered
// set before the mod will place an extractor on it. Mirrors the Python
// discovered_nodes() logic in world_state.py:
//   a node is discovered if an extractor is already placed within
//   EXTRACTOR_SNAP_RADIUS of it, OR it falls inside any radar tower's scan
//   radius.
//
// Part of the FactorySpawnerAI fork (MIT, see mod/LICENSE).

#pragma once

#include "CoreMinimal.h"

class UWorld;

namespace NodeDiscovery
{
	/** A miner placed within this 2D distance counts as "on" the node (uu). */
	constexpr float EXTRACTOR_SNAP_RADIUS = 1000.f;

	/**
	 * Returns true if the node at (X,Y,Z) is discovered:
	 *   1. an existing AFGBuildableResourceExtractor is within
	 *      EXTRACTOR_SNAP_RADIUS (2D), OR
	 *   2. the node lies within any radar tower's scan radius.
	 */
	bool IsNodeDiscovered(UWorld* World, float X, float Y, float Z);
}
