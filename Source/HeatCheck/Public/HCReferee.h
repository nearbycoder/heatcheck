#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HCReferee.generated.h"

class UAnimSequence;
class UHCAnimInstance;
class USkeletalMeshComponent;

UCLASS()
class HEATCHECK_API AHCReferee : public AActor
{
	GENERATED_BODY()
public:
	AHCReferee();
	static constexpr float ReleaseTime = 27.f / 30.f;
	void LineUp();
	FVector PoseToss(float Time);
	void FollowThrough();
	void TrackPlay(float Dt, const FVector& Ball);

private:
	UPROPERTY() TObjectPtr<USkeletalMeshComponent> Body;
	UPROPERTY() TObjectPtr<UHCAnimInstance> Anim;
	UPROPERTY() TObjectPtr<UAnimSequence> Toss;
	UPROPERTY() TObjectPtr<UAnimSequence> Run;
	UPROPERTY() TObjectPtr<UAnimSequence> Idle;
	float SinceRelease = -1.f;
	bool bOnSideline = false;
	bool bJogging = false;
};
