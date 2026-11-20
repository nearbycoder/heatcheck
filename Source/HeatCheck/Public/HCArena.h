#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HCArena.generated.h"

namespace Scalability { struct FQualityLevels; }
class UStaticMeshComponent;
class UDirectionalLightComponent;
class USkyLightComponent;
class URectLightComponent;
class USpotLightComponent;
class UBoxComponent;
class UMaterialParameterCollection;

/** The HEAT CHECK Arena: court, bowl, crowd, boards and all lighting. Built from the imported Blender meshes. */
UCLASS()
class HEATCHECK_API AHCArena : public AActor
{
	GENERATED_BODY()
public:
	AHCArena();
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void Tick(float DeltaSeconds) override;

	/** 0..1 crowd energy; drives the crowd bounce material and lights. */
	void Excite(float Amount);
	void Flash(float Amount);
	float Excitement = 0.f;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UBoxComponent> FloorCollision;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UDirectionalLightComponent> KeyLight;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkyLightComponent> SkyLight;
	UPROPERTY(Transient)
	TArray<TObjectPtr<URectLightComponent>> CourtLights;
	UPROPERTY(Transient)
	TArray<TObjectPtr<USpotLightComponent>> CrowdLights;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> Pieces;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialParameterCollection> MPC;

private:
	void BuildFromAssets();
	void BuildLights();
	void ApplyQuality(const Scalability::FQualityLevels& Quality);
	float TargetExcitement = 0.f;
	float FlashAmt = 0.f;
	float Time = 0.f;
};
