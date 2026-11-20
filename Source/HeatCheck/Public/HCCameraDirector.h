#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HCCameraDirector.generated.h"

class UCameraComponent;

/** Broadcast-style sideline camera that tracks the ball, zooms on dunks and orbits in menus. */
UCLASS()
class HEATCHECK_API AHCCameraDirector : public AActor
{
	GENERATED_BODY()
public:
	AHCCameraDirector();
	virtual void Tick(float DeltaSeconds) override;
	void Shake(float Amount) { ShakeAmt = FMath::Max(ShakeAmt, Amount); }
	void Snap() { bSnap = true; }

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UCameraComponent> Camera;

private:
	FVector Focus = FVector::ZeroVector;
	float Zoom = 1.f;
	float ShakeAmt = 0.f;
	float Time = 0.f;
	bool bSnap = true;
};
