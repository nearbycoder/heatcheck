#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HCBall.generated.h"

class AHCCharacter;
class AHCGameMode;
class UHCSpriteFX;
class UStaticMeshComponent;

enum class EHCBallState : uint8
{
	Official, // held by the referee until the tip release
	Held,     // in a player's hands (dribbling or holding)
	Shot,     // field goal attempt in flight
	Pass,     // pass in flight
	Loose,    // free physics (rebounds, steals, tip-offs)
	Dead      // after a score / violation: physics only, nobody can grab it
};

enum class EHCBallHold : uint8 { Dribble, TwoHands, RightHand };

UCLASS()
class HEATCHECK_API AHCBall : public AActor
{
	GENERATED_BODY()
public:
	AHCBall();
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	// --- state changes -----------------------------------------------------
	void GiveTo(AHCCharacter* NewHolder);
	void SetLoose(const FVector& Velocity, AHCCharacter* Toucher = nullptr);
	void SetDead();
	void LaunchShot(AHCCharacter* InShooter, int32 HoopIndex, int32 Points, bool bMake, bool bFire, float FlightTime, const FVector& Target);
	void LaunchPass(AHCCharacter* From, AHCCharacter* To, bool bAlley, const FVector& AlleyPoint);
	void DunkThrough(int32 HoopIndex);
	void HoldForTip(const FVector& Grip);
	void Toss(const FVector& From, float UpSpeed);

	// --- queries -----------------------------------------------------------
	EHCBallState GetState() const { return State; }
	AHCCharacter* GetHolder() const { return Holder; }
	AHCCharacter* GetShooter() const { return Shooter; }
	AHCCharacter* GetPassTarget() const { return PassTo; }
	AHCCharacter* GetPasser() const { return PassFrom; }
	bool IsAlleyPass() const { return bAlley; }
	float RemainingPassTime() const { return FMath::Max(0.f, PassDuration - PassT); }
	FVector GetVelocity() const { return Velocity; }
	int32 GetShotHoop() const { return ShotHoop; }
	int32 GetShotPoints() const { return ShotPoints; }
	bool IsShotMake() const { return bShotMake; }
	bool WasShotFire() const { return bShotFire; }
	float GetShotTime() const { return ShotT; }
	float GetShotDuration() const { return ShotDuration; }
	bool HasTouchedRim() const { return bRimTouched; }
	bool IsDescending() const { return Velocity.Z < 0.f; }
	/** Predict where the ball will be after T seconds of free flight (no collisions). */
	FVector PredictPosition(float T) const;
	/** Rough landing point near the floor-level for rebound positioning. */
	FVector PredictRebound() const;
	int32 LastTouchTeam = -1;
	AHCCharacter* LastShooter = nullptr;
	bool bFireTrail = false;

	/** Shot was blocked/deflected by a defender. */
	void Deflect(const FVector& NewVelocity, AHCCharacter* By);

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Mesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UHCSpriteFX> FireFX;

private:
	AHCGameMode* GM() const;
	void UpdateHeld(float Dt);
	void UpdateShot(float Dt);
	void UpdatePass(float Dt);
	void StepPhysics(float Dt, bool bCollide);
	void CollideRim(int32 HoopIndex, FVector& P, FVector& V);
	void CollideBackboard(int32 HoopIndex, FVector& P, FVector& V);
	void CheckThroughHoop(int32 HoopIndex, const FVector& PrevP, const FVector& P);
	void SpinVisual(float Dt);

	EHCBallState State = EHCBallState::Loose;
	UPROPERTY(Transient)
	TObjectPtr<AHCCharacter> Holder = nullptr;
	FVector Velocity = FVector::ZeroVector;
	FVector Pos = FVector::ZeroVector;
	float DribblePhasePrev = 0.f;

	// shot
	UPROPERTY(Transient)
	TObjectPtr<AHCCharacter> Shooter = nullptr;
	int32 ShotHoop = 0;
	int32 ShotPoints = 2;
	bool bShotMake = false;
	bool bShotFire = false;
	bool bShotScored = false;
	bool bRimTouched = false;
	bool bAnalytic = false;
	float ShotT = 0.f;
	float ShotDuration = 1.f;
	FVector ShotStart = FVector::ZeroVector;
	FVector ShotV0 = FVector::ZeroVector;
	float NetDragTime = 0.f;

	// pass
	UPROPERTY(Transient)
	TObjectPtr<AHCCharacter> PassFrom = nullptr;
	UPROPERTY(Transient)
	TObjectPtr<AHCCharacter> PassTo = nullptr;
	bool bAlley = false;
	FVector AlleyPoint = FVector::ZeroVector;
	FVector PassStart = FVector::ZeroVector;
	float PassT = 0.f;
	float PassDuration = 0.5f;
	TSet<TObjectPtr<AHCCharacter>> InterceptTried;

	FQuat SpinQuat = FQuat::Identity;
	float SoundCooldown = 0.f;
	float FireEmitAccum = 0.f;
	float SinceShot = 100.f;
	mutable TWeakObjectPtr<AHCGameMode> CachedGM;
};
