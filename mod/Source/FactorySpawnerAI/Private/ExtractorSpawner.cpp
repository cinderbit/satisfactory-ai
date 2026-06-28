// ExtractorSpawner.cpp — see ExtractorSpawner.h

#include "ExtractorSpawner.h"

#include "EngineUtils.h"                       // TActorIterator
#include "Resources/FGResourceNode.h"
#include "Buildables/FGBuildableResourceExtractor.h"

namespace
{
	// Asset paths for each extractor type, indexed by tier-1.
	// VERIFY these against your CSS content browser — CSS occasionally renames
	// assets between updates (docs/step5_cpp_spec.md §4).
	const TMap<FString, TArray<FString>>& ClassPathMap()
	{
		static const TMap<FString, TArray<FString>> Map = {
			{ TEXT("Miner"), {
				TEXT("/Game/FactoryGame/Buildable/Factory/MinerMK1/Build_MinerMk1.Build_MinerMk1_C"),
				TEXT("/Game/FactoryGame/Buildable/Factory/MinerMK2/Build_MinerMk2.Build_MinerMk2_C"),
				TEXT("/Game/FactoryGame/Buildable/Factory/MinerMK3/Build_MinerMk3.Build_MinerMk3_C"),
			}},
			{ TEXT("WaterExtractor"), {
				TEXT("/Game/FactoryGame/Buildable/Factory/WaterPump/Build_WaterPump.Build_WaterPump_C"),
			}},
			{ TEXT("ResourceExtractor"), {
				TEXT("/Game/FactoryGame/Buildable/Factory/FrackingExtractor/Build_FrackingExtractor.Build_FrackingExtractor_C"),
			}},
		};
		return Map;
	}
}

namespace ExtractorSpawner
{
	TSubclassOf<AFGBuildableResourceExtractor> GetExtractorClass(
		const FString& MachineType, int32 Tier)
	{
		const TArray<FString>* Paths = ClassPathMap().Find(MachineType);
		if (!Paths || Paths->Num() == 0)
		{
			return nullptr;
		}

		const int32 Idx = FMath::Clamp(Tier - 1, 0, Paths->Num() - 1);
		const FSoftClassPath ClassPath((*Paths)[Idx]);
		return Cast<UClass>(ClassPath.TryLoad());
	}

	AFGResourceNode* FindNearestResourceNode(
		UWorld* World, float X, float Y, float Z, float SearchRadius)
	{
		if (!World)
		{
			return nullptr;
		}

		const FVector Target(X, Y, Z);
		AFGResourceNode* Best = nullptr;
		float BestDist = SearchRadius;

		for (TActorIterator<AFGResourceNode> It(World); It; ++It)
		{
			const float Dist = FVector::Dist2D(It->GetActorLocation(), Target);
			if (Dist <= BestDist)
			{
				BestDist = Dist;
				Best = *It;
			}
		}

		return Best;
	}

	AFGBuildableResourceExtractor* SpawnExtractor(
		UWorld* World, const FExtractorToken& Token, FString& OutError)
	{
		if (!World)
		{
			OutError = TEXT("No world context");
			return nullptr;
		}

		// 1. Locate the node.
		AFGResourceNode* Node = FindNearestResourceNode(
			World, Token.nodeX, Token.nodeY, Token.nodeZ,
			/*SearchRadius=*/1000.f);
		if (!Node)
		{
			OutError = FString::Printf(
				TEXT("No resource node within 1000uu of X=%.0f Y=%.0f"),
				Token.nodeX, Token.nodeY);
			return nullptr;
		}

		if (Node->IsOccupied())
		{
			OutError = FString::Printf(
				TEXT("Node at X=%.0f Y=%.0f is already occupied"),
				Token.nodeX, Token.nodeY);
			return nullptr;
		}

		// 2. Resolve the buildable class.
		TSubclassOf<AFGBuildableResourceExtractor> ExtractorClass =
			GetExtractorClass(Token.machineType, Token.minerTier);
		if (!ExtractorClass)
		{
			OutError = FString::Printf(
				TEXT("Unknown extractor type '%s' (tier %d)"),
				*Token.machineType, Token.minerTier);
			return nullptr;
		}

		// 3. Spawn aligned to the node transform.
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride =
			ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

		AFGBuildableResourceExtractor* Extractor =
			World->SpawnActor<AFGBuildableResourceExtractor>(
				ExtractorClass, Node->GetActorTransform(), Params);
		if (!Extractor)
		{
			OutError = FString::Printf(
				TEXT("SpawnActor failed for '%s'"), *Token.machineType);
			return nullptr;
		}

		// 4. Bind the extractor to its node.
		//    NOTE: verify the binding API against CSS headers — older builds
		//    use SetResourceNode(); some expose it via the extraction component.
		Extractor->SetResourceNode(Node);
		Node->SetIsOccupied(true);

		// 5. Apply clock speed via RCO (multiplayer-safe). Upstream already
		//    drives Server_PasteSettings for manufacturers — reuse that path
		//    so dedicated-server overclocking stays correct.
		if (!FMath::IsNearlyEqual(Token.clockSpeed, 100.f))
		{
			const float Potential = FMath::Clamp(Token.clockSpeed / 100.f, 0.01f, 2.5f);
			Extractor->SetPendingPotential(Potential);
			// For dedicated-server correctness the caller should additionally
			// route this through the RCO Server_PasteSettings path used by the
			// manufacturer spawner. See docs/step5_cpp_spec.md §4.
		}

		return Extractor;
	}
}
