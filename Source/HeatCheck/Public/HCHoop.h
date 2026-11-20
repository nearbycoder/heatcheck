#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HCHoop.generated.h"

class UStaticMeshComponent;
class UHCSpriteFX;

/** One basket: stanchion, glass, frame, rim (shakes) and net (swishes / burns). */
UCLASS()
class HEATCHECK_API AHCHoop : public AActor
{
	GENERATED_BODY()
public:
	AHCHoop();
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	/** 0 = basket at -X, 1 = basket at +X. */
	void SetIndex(int32 InIndex);
	int32 Index = 0;

	FVector RimCenter() const;
	FVector FloorUnderRim() const;
	/** Unit vector pointing from this basket toward center court. */
	FVector Facing() const;

	void Shake(float Amount);
	void Swish(float Amount);
	void SetNetFire(float Seconds);
	void FlashGlass();

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Stanchion;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Glass;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Frame;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Rim;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Net;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UHCSpriteFX> FX;

private:
	float ShakeAmt = 0.f;
	float ShakeT = 0.f;
	float SwishAmt = 0.f;
	float SwishT = 0.f;
	float FireTime = 0.f;
	float FireAccum = 0.f;
};
