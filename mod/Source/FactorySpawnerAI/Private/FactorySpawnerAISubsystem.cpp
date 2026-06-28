// FactorySpawnerAISubsystem.cpp — see FactorySpawnerAISubsystem.h

#include "FactorySpawnerAISubsystem.h"

#include "HttpServerModule.h"
#include "HttpServerResponse.h"
#include "IHttpRouter.h"
#include "JsonObjectConverter.h"
#include "Async/Async.h"

#include "NodeDiscovery.h"
#include "ExtractorSpawner.h"

// Upstream generator — reused unchanged. The fork only adds the origin +
// blueprint parameters to Generate() (docs/step5_cpp_spec.md §7).
#include "BuildPlanGenerator.h"

namespace
{
	TUniquePtr<FHttpServerResponse> JsonResponse(const FString& Body, int32 Code)
	{
		auto Resp = FHttpServerResponse::Create(Body, TEXT("application/json"));
		Resp->Code = static_cast<EHttpServerResponseCodes>(Code);
		return Resp;
	}

	FString OkBody(const FString& Message)
	{
		return FString::Printf(
			TEXT("{\"status\":\"ok\",\"message\":\"%s\"}"), *Message);
	}

	FString ErrorBody(const FString& Message, const TArray<FString>& Errors = {})
	{
		FString ErrArray;
		for (int32 i = 0; i < Errors.Num(); ++i)
		{
			ErrArray += FString::Printf(TEXT("\"%s\""),
				*Errors[i].ReplaceCharWithEscapedChar());
			if (i + 1 < Errors.Num()) ErrArray += TEXT(",");
		}
		return FString::Printf(
			TEXT("{\"status\":\"error\",\"message\":\"%s\",\"errors\":[%s]}"),
			*Message, *ErrArray);
	}
}

AFactorySpawnerAISubsystem::AFactorySpawnerAISubsystem()
{
	PrimaryActorTick.bCanEverTick = false;
}

void AFactorySpawnerAISubsystem::BeginPlay()
{
	Super::BeginPlay();

	// Only the server (or single-player host) should listen — clients must not.
	if (HasAuthority())
	{
		StartHttpListener();
	}
}

void AFactorySpawnerAISubsystem::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	StopHttpListener();
	Super::EndPlay(EndPlayReason);
}

void AFactorySpawnerAISubsystem::StartHttpListener()
{
	FHttpServerModule& Http = FHttpServerModule::Get();
	TSharedPtr<IHttpRouter> Router = Http.GetHttpRouter(ListenPort);
	if (!Router.IsValid())
	{
		UE_LOG(LogTemp, Error,
			TEXT("[FactorySpawnerAI] Failed to get HTTP router on port %d"),
			ListenPort);
		return;
	}

	Router->BindRoute(
		FHttpPath(TEXT("/health")), EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateUObject(this, &AFactorySpawnerAISubsystem::HandleHealth));

	Router->BindRoute(
		FHttpPath(TEXT("/build")), EHttpServerRequestVerbs::VERB_POST,
		FHttpRequestHandler::CreateUObject(this, &AFactorySpawnerAISubsystem::HandleBuild));

	BoundRouters.Add(Router);
	Http.StartAllListeners();

	UE_LOG(LogTemp, Display,
		TEXT("[FactorySpawnerAI] HTTP listener started on port %d"), ListenPort);
}

void AFactorySpawnerAISubsystem::StopHttpListener()
{
	if (BoundRouters.Num() > 0)
	{
		FHttpServerModule::Get().StopAllListeners();
		BoundRouters.Reset();
	}
}

bool AFactorySpawnerAISubsystem::HandleHealth(
	const FHttpServerRequest& /*Request*/,
	const FHttpResultCallback& OnComplete)
{
	OnComplete(JsonResponse(TEXT("{\"status\":\"ok\"}"), 200));
	return true;
}

bool AFactorySpawnerAISubsystem::HandleBuild(
	const FHttpServerRequest& Request,
	const FHttpResultCallback& OnComplete)
{
	// Body arrives as UTF-8 bytes.
	const FString Body = FString(
		UTF8_TO_TCHAR(reinterpret_cast<const char*>(Request.Body.GetData())));

	FBuildRequest BuildReq;
	if (!FJsonObjectConverter::JsonObjectStringToUStruct(Body, &BuildReq, 0, 0))
	{
		OnComplete(JsonResponse(ErrorBody(TEXT("Invalid JSON")), 400));
		return true;
	}

	// Validate node discovery up front — reject the whole request if any node
	// is not in the player's discovered set. No partial spawning.
	UWorld* World = GetWorld();
	TArray<FString> ValidationErrors;
	for (const FExtractorToken& ET : BuildReq.extractors)
	{
		if (!NodeDiscovery::IsNodeDiscovered(World, ET.nodeX, ET.nodeY, ET.nodeZ))
		{
			ValidationErrors.Add(FString::Printf(
				TEXT("Node at X=%.0f Y=%.0f is not in the player's discovered set"),
				ET.nodeX, ET.nodeY));
		}
	}
	if (ValidationErrors.Num() > 0)
	{
		OnComplete(JsonResponse(
			ErrorBody(TEXT("Validation failed"), ValidationErrors), 422));
		return true;
	}

	// Spawning must happen on the game thread. Hop over, then complete the
	// HTTP response from there.
	AsyncTask(ENamedThreads::GameThread,
		[this, BuildReq, OnComplete]()
		{
			ExecuteBuild(BuildReq, OnComplete);
		});

	return true; // response delivered asynchronously
}

void AFactorySpawnerAISubsystem::ExecuteBuild(
	const FBuildRequest& BuildReq,
	const FHttpResultCallback& OnComplete)
{
	UWorld* World = GetWorld();
	TArray<FString> Errors;

	// 1. Extractors first (inputs before processors).
	int32 ExtractorCount = 0;
	for (const FExtractorToken& ET : BuildReq.extractors)
	{
		FString Err;
		if (ExtractorSpawner::SpawnExtractor(World, ET, Err))
		{
			++ExtractorCount;
		}
		else
		{
			Errors.Add(Err);
		}
	}

	// 2. Manufacturer rows via the reused upstream generator, anchored at the
	//    requested origin instead of the player's location.
	int32 MachineCount = 0;
	if (Errors.Num() == 0)
	{
		ABuildPlanGenerator* Generator = ABuildPlanGenerator::Get(World);
		if (!Generator)
		{
			Errors.Add(TEXT("BuildPlanGenerator unavailable"));
		}
		else
		{
			// Convert manufacturer tokens into the upstream token type.
			TArray<FFactoryCommandToken> Tokens;
			Tokens.Reserve(BuildReq.manufacturers.Num());
			for (const FManufacturerToken& MT : BuildReq.manufacturers)
			{
				FFactoryCommandToken T;
				T.Count       = MT.count;
				T.MachineType = MT.machineType;
				T.Recipe      = MT.recipe;
				T.Clock       = MT.clockSpeed;
				Tokens.Add(T);
			}

			const FVector Origin(BuildReq.originX, BuildReq.originY, BuildReq.originZ);
			MachineCount = Generator->Generate(Tokens, Origin, BuildReq.writeBlueprint);
		}
	}

	const FString Msg = FString::Printf(
		TEXT("Spawned %d machines, %d extractors."), MachineCount, ExtractorCount);

	OnComplete(Errors.Num() == 0
		? JsonResponse(OkBody(Msg), 200)
		: JsonResponse(ErrorBody(TEXT("Partial failure"), Errors), 500));
}
