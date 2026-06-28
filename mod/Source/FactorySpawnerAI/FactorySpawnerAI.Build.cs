// FactorySpawnerAI.Build.cs
//
// Build rules for the FactorySpawnerAI module. Adds HTTPServer + Json on top
// of the FactoryGame/SML dependencies the upstream FactorySpawner already uses.

using UnrealBuildTool;

public class FactorySpawnerAI : ModuleRules
{
	public FactorySpawnerAI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			// HTTP listener + JSON (new in the fork)
			"HTTPServer",
			"Json",
			"JsonUtilities",
			// Satisfactory + SML (same set upstream FactorySpawner uses)
			"FactoryGame",
			"SML",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Slate",
			"SlateCore",
		});

		// FactoryGame headers expect these.
		PublicDefinitions.Add("WITH_INDIRECTBUILDER=0");
	}
}
