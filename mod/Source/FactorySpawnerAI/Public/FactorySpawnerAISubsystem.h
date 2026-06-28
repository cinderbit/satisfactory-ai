// FactorySpawnerAISubsystem.h
//
// Mod subsystem that owns the HTTP listener and bridges incoming build
// requests into the (reused) upstream BuildPlanGenerator. This REPLACES
// upstream's chat-command parser entry point; everything below Generate()
// is reused unchanged.
//
// Part of the FactorySpawnerAI fork (MIT, see mod/LICENSE).

#pragma once

#include "CoreMinimal.h"
#include "Subsystem/ModSubsystem.h"
#include "HttpServerRequest.h"
#include "HttpResultCallback.h"
#include "BuildRequestTypes.h"
#include "FactorySpawnerAISubsystem.generated.h"

UCLASS()
class FACTORYSPAWNERAI_API AFactorySpawnerAISubsystem : public AModSubsystem
{
	GENERATED_BODY()

public:
	AFactorySpawnerAISubsystem();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	/** Listener port. Exposed for a future mod config option. */
	UPROPERTY(EditDefaultsOnly, Category = "FactorySpawnerAI")
	int32 ListenPort = 8082;

private:
	void StartHttpListener();
	void StopHttpListener();

	/** GET /health */
	bool HandleHealth(const FHttpServerRequest& Request,
	                  const FHttpResultCallback& OnComplete);

	/** POST /build */
	bool HandleBuild(const FHttpServerRequest& Request,
	                 const FHttpResultCallback& OnComplete);

	/** Runs the actual spawn work on the game thread. */
	void ExecuteBuild(const FBuildRequest& BuildReq,
	                  const FHttpResultCallback& OnComplete);

	TArray<TSharedPtr<class IHttpRouter>> BoundRouters;
};
