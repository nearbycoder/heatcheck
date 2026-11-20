#include "HCArena.h"
#include "HeatCheck.h"
#include "Scalability.h"
#include "Components/StaticMeshComponent.h"
#include "Components/BoxComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/TextureCube.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Materials/MaterialParameterCollection.h"
#include "Kismet/KismetMaterialLibrary.h"

AHCArena::AHCArena()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;

	FloorCollision = CreateDefaultSubobject<UBoxComponent>(TEXT("FloorCollision"));
	FloorCollision->SetupAttachment(Root);
	FloorCollision->SetBoxExtent(FVector(6000.f, 6000.f, 50.f));
	FloorCollision->SetRelativeLocation(FVector(0.f, 0.f, -50.f));
	FloorCollision->SetCollisionProfileName(TEXT("BlockAll"));
	FloorCollision->SetHiddenInGame(true);

	KeyLight = CreateDefaultSubobject<UDirectionalLightComponent>(TEXT("KeyLight"));
	KeyLight->SetupAttachment(Root);
	KeyLight->SetRelativeRotation(FRotator(-58.f, -102.f, 0.f));
	KeyLight->SetIntensity(3.2f);
	KeyLight->SetLightColor(FLinearColor(1.0f, 0.95f, 0.88f));
	KeyLight->SetCastShadows(true);
	KeyLight->SetMobility(EComponentMobility::Movable);

	SkyLight = CreateDefaultSubobject<USkyLightComponent>(TEXT("SkyLight"));
	SkyLight->SetupAttachment(Root);
	SkyLight->SetMobility(EComponentMobility::Movable);
	SkyLight->SourceType = ESkyLightSourceType::SLS_SpecifiedCubemap;
	SkyLight->bRealTimeCapture = false;
	SkyLight->SetIntensity(1.0f);
	SkyLight->SetLightColor(FLinearColor(0.75f, 0.80f, 1.0f));
	SkyLight->bLowerHemisphereIsBlack = false;
}

void AHCArena::BeginPlay()
{
	Super::BeginPlay();
	if (UTextureCube* Cube = LoadObject<UTextureCube>(nullptr, TEXT("/Engine/EngineResources/GrayLightTextureCube.GrayLightTextureCube")))
	{
		SkyLight->SetCubemap(Cube);
	}
	BuildFromAssets();
	BuildLights();
	ApplyQuality(Scalability::GetQualityLevels());
	Scalability::OnScalabilitySettingsChanged.AddUObject(this, &AHCArena::ApplyQuality);
	MPC = LoadObject<UMaterialParameterCollection>(nullptr, TEXT("/Game/HeatCheck/Materials/MPC_HeatCheck.MPC_HeatCheck"));
}

void AHCArena::EndPlay(const EEndPlayReason::Type Reason)
{
	Scalability::OnScalabilitySettingsChanged.RemoveAll(this);
	Super::EndPlay(Reason);
}

void AHCArena::ApplyQuality(const Scalability::FQualityLevels& Quality)
{
	for (UStaticMeshComponent* Piece : Pieces)
	{
		const FString Name = Piece->GetName();
		if (Name.Contains(TEXT("Crowd_")))
		{
			const bool bUpperDeck = Name.Contains(TEXT("Crowd_Upper"));
			Piece->SetVisibility(!bUpperDeck || Quality.ViewDistanceQuality >= 1);
			Piece->SetEvaluateWorldPositionOffset(!bUpperDeck || Quality.ViewDistanceQuality >= 2);
		}
	}
	for (int32 I = 0; I < CrowdLights.Num(); ++I)
	{
		CrowdLights[I]->SetVisibility(Quality.ShadingQuality >= 2 || (Quality.ShadingQuality == 1 && (I == 0 || I == 3)));
	}
	// The central softbox adds a second shadow under the athletes on Cinematic.
	if (!CourtLights.IsEmpty()) { CourtLights.Last()->SetCastShadows(Quality.ShadowQuality >= 4); }
}

void AHCArena::BuildFromAssets()
{
	// Explicit list (cooked builds load the asset registry asynchronously, so it can't be relied on at BeginPlay).
	TArray<FString> Names = {
		TEXT("SM_CourtFloor"), TEXT("SM_ArenaFloor"), TEXT("SM_ArenaBowl"), TEXT("SM_Banners"),
		TEXT("SM_Crowd_LowerFar"), TEXT("SM_Crowd_LowerLeft"), TEXT("SM_Crowd_LowerNear"), TEXT("SM_Crowd_LowerRight"),
		TEXT("SM_Crowd_UpperFar"), TEXT("SM_Crowd_UpperLeft"), TEXT("SM_Crowd_UpperNear"), TEXT("SM_Crowd_UpperRight"),
		TEXT("SM_Jumbotron"), TEXT("SM_LedRibbon_Courtside"), TEXT("SM_LedRibbon_Facade"), TEXT("SM_LightRig"),
		TEXT("SM_ScorerTable"), TEXT("SM_TeamBenches") };
#if WITH_EDITOR
	// in the editor, also pick up any newly generated arena pieces automatically
	IAssetRegistry& AR = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
	AR.ScanPathsSynchronous({ TEXT("/Game/HeatCheck/Meshes") }, true);
	TArray<FAssetData> Assets;
	AR.GetAssetsByPath(FName(TEXT("/Game/HeatCheck/Meshes")), Assets, true);
	static const TCHAR* Skip[] = { TEXT("SM_Hoop"), TEXT("SM_Backboard"), TEXT("SM_Rim"), TEXT("SM_Net"), TEXT("SM_Ball") };
	for (const FAssetData& A : Assets)
	{
		const FString N = A.AssetName.ToString();
		bool bSkip = !N.StartsWith(TEXT("SM_"));
		for (const TCHAR* S : Skip)
		{
			bSkip |= N.StartsWith(S);
		}
		if (!bSkip)
		{
			Names.AddUnique(N);
		}
	}
#endif
	for (const FString& Name : Names)
	{
		const FString Path = FString::Printf(TEXT("/Game/HeatCheck/Meshes/%s.%s"), *Name, *Name);
		UStaticMesh* SM = LoadObject<UStaticMesh>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (!SM)
		{
			continue;
		}
		UStaticMeshComponent* C = NewObject<UStaticMeshComponent>(this, FName(*(TEXT("Arena_") + Name)));
		C->SetStaticMesh(SM);
		C->SetMobility(EComponentMobility::Movable);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetGenerateOverlapEvents(false);
		C->SetupAttachment(Root);
		const bool bCrowd = Name.Contains(TEXT("Crowd"));
		// only courtside furniture casts shadows; the bowl, roof, truss, jumbotron and crowd would
		// otherwise stripe the floor with the key light's shadows
		const bool bCaster = Name.Contains(TEXT("ScorerTable")) || Name.Contains(TEXT("Bench"));
		C->SetCastShadow(bCaster);
		if (bCrowd)
		{
			C->bEvaluateWorldPositionOffset = true;
		}
		C->RegisterComponent();
		Pieces.Add(C);
	}
	UE_LOG(LogHeatCheck, Display, TEXT("Arena built from %d pieces"), Pieces.Num());
}

void AHCArena::BuildLights()
{
	// Big soft area lights over the court (broadcast lighting rig)
	const FVector2D Spots[] = { FVector2D(-850.f, -250.f), FVector2D(850.f, -250.f), FVector2D(-850.f, 350.f), FVector2D(850.f, 350.f), FVector2D(0.f, 50.f) };
	for (int32 i = 0; i < UE_ARRAY_COUNT(Spots); ++i)
	{
		URectLightComponent* L = NewObject<URectLightComponent>(this);
		L->SetupAttachment(Root);
		L->SetMobility(EComponentMobility::Movable);
		L->SetRelativeLocation(FVector(Spots[i].X, Spots[i].Y, 1650.f));
		L->SetRelativeRotation(FRotator(-90.f, 0.f, 0.f));
		L->SetIntensityUnits(ELightUnits::Unitless);
		L->SetIntensity(i == 4 ? 900.f : 650.f);
		L->SetSourceWidth(900.f);
		L->SetSourceHeight(500.f);
		L->SetAttenuationRadius(4200.f);
		L->SetBarnDoorAngle(60.f);
		L->SetLightColor(FLinearColor(1.f, 0.96f, 0.9f));
		L->SetCastShadows(false);
		L->RegisterComponent();
		CourtLights.Add(L);
	}
	// colored spots sweeping the crowd for atmosphere
	const FLinearColor Cols[] = { FLinearColor(1.f, 0.25f, 0.05f), FLinearColor(1.f, 0.6f, 0.05f), FLinearColor(0.2f, 0.5f, 1.f), FLinearColor(1.f, 0.25f, 0.05f) };
	for (int32 i = 0; i < 4; ++i)
	{
		USpotLightComponent* L = NewObject<USpotLightComponent>(this);
		L->SetupAttachment(Root);
		L->SetMobility(EComponentMobility::Movable);
		L->SetRelativeLocation(FVector(-1500.f + i * 1000.f, 0.f, 1900.f));
		L->SetIntensityUnits(ELightUnits::Unitless);
		L->SetIntensity(2500.f);
		L->SetOuterConeAngle(16.f);
		L->SetInnerConeAngle(8.f);
		L->SetAttenuationRadius(6000.f);
		L->SetLightColor(Cols[i]);
		L->SetCastShadows(false);
		L->RegisterComponent();
		CrowdLights.Add(L);
	}
}

void AHCArena::Excite(float Amount)
{
	TargetExcitement = FMath::Clamp(FMath::Max(TargetExcitement, Amount), 0.f, 1.f);
}

void AHCArena::Flash(float Amount)
{
	FlashAmt = FMath::Max(FlashAmt, Amount);
}

void AHCArena::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Time += DeltaSeconds;
	Excitement = FMath::FInterpTo(Excitement, TargetExcitement, DeltaSeconds, 6.f);
	TargetExcitement = FMath::Max(0.12f, TargetExcitement - DeltaSeconds * 0.22f);
	FlashAmt = FMath::Max(0.f, FlashAmt - DeltaSeconds * 2.5f);
	if (MPC)
	{
		UKismetMaterialLibrary::SetScalarParameterValue(this, MPC, TEXT("CrowdExcitement"), Excitement);
		UKismetMaterialLibrary::SetScalarParameterValue(this, MPC, TEXT("ArenaFlash"), FlashAmt);
	}
	// sweep the crowd spots
	for (int32 i = 0; i < CrowdLights.Num(); ++i)
	{
		USpotLightComponent* L = CrowdLights[i];
		if (!L->IsVisible()) { continue; }
		const float A = Time * (0.35f + 0.08f * i) + i * 1.7f;
		const FVector Target(FMath::Sin(A) * 2600.f, (i % 2 == 0 ? -1.f : 1.f) * (1800.f + 600.f * FMath::Sin(A * 1.3f)), 400.f);
		L->SetWorldRotation((Target - L->GetComponentLocation()).Rotation());
		L->SetIntensity(1800.f + 5000.f * Excitement + 8000.f * FlashAmt);
	}
	for (URectLightComponent* L : CourtLights)
	{
		L->SetIntensity(650.f * (1.f + FlashAmt * 0.8f));
	}
}
