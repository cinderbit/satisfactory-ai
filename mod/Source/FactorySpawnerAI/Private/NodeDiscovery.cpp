// NodeDiscovery.cpp — see NodeDiscovery.h

#include "NodeDiscovery.h"

#include "EngineUtils.h"                       // TActorIterator
#include "Resources/FGResourceNode.h"
#include "Buildables/FGBuildableResourceExtractor.h"
#include "Buildables/FGBuildableRadarTower.h"

namespace NodeDiscovery
{
	bool IsNodeDiscovered(UWorld* World, float X, float Y, float Z)
	{
		if (!World)
		{
			return false;
		}

		const FVector NodeLoc(X, Y, Z);

		// Check 1: an extractor already placed on/near this node.
		for (TActorIterator<AFGBuildableResourceExtractor> It(World); It; ++It)
		{
			if (FVector::Dist2D(It->GetActorLocation(), NodeLoc) <= EXTRACTOR_SNAP_RADIUS)
			{
				return true;
			}
		}

		// Check 2: inside a radar tower's scan radius.
		for (TActorIterator<AFGBuildableRadarTower> It(World); It; ++It)
		{
			// NOTE: verify the accessor name against the CSS headers for your
			// build. GetRevealRadius()/GetScanRadius() have both appeared.
			const float Radius = It->GetRevealRadius();
			if (FVector::Dist2D(It->GetActorLocation(), NodeLoc) <= Radius)
			{
				return true;
			}
		}

		return false;
	}
}
