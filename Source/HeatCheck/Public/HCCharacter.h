#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "HCTypes.h"
#include "HCBall.h"
#include "HCCharacter.generated.h"

class AHCGameMode;
class UHCAnimInstance;
class UHCSpriteFX;
class UMaterialInstanceDynamic;

enum class EHCPState : uint8
{
	Free,
	ShootWindup,
	ShootAir,
	Layup,
	DunkWindup,
	DunkAir,
	DunkHang,
	DunkLand,
	Pass,
	Shove,
	Stagger,
	Steal,
	Block,
	KnockedDown,
	GetUp,
	Celebrate,
	Inbound
};

enum class EHCDunkStyle : uint8 { TwoHand, Windmill, Spin360, Reverse, Flip };

struct FHCStats
{
	int32 Points = 0, FGM = 0, FGA = 0, TPM = 0, TPA = 0, Dunks = 0, Steals = 0, Blocks = 0, Shoves = 0, Rebounds = 0, Assists = 0;
};

UCLASS()
class HEATCHECK_API AHCCharacter : public ACharacter
{
	GENERATED_BODY()
public:
	AHCCharacter();

	void Setup(int32 InTeam, int32 InSlot, const FHCTeamDef& TeamDef, const FHCPlayerDef& Def);
	void ApplyHeadScale(float S);
	virtual void Tick(float DeltaSeconds) override;
	virtual void Landed(const FHitResult& Hit) override;

	// --- identity ------------------------------------------------------------
	int32 Team = 0;
	int32 Slot = 0;
	FHCPlayerDef Def;
	FLinearColor TeamColor = FLinearColor::White;
	bool bHuman = false;
	int32 HumanIndex = -1;

	// --- runtime -------------------------------------------------------------
	FHCInput Input;
	float Turbo = 1.f;
	int32 Streak = 0;       // consecutive baskets since the opponents last scored
	bool bOnFire = false;
	int32 FireMakes = 0;
	FHCStats Stats;
	EHCPState State = EHCPState::Free;
	float StateTime = 0.f;
	float StealCooldown = 0.f;
	float ShoveCooldown = 0.f;
	float ActionLock = 0.f;  // brief lockout after catching etc.

	// --- queries -------------------------------------------------------------
	bool HasBall() const;
	bool IsAirborne() const;
	bool IsDown() const { return State == EHCPState::KnockedDown || State == EHCPState::GetUp; }
	bool CanReceiveBall() const { return !IsDown() && State != EHCPState::Stagger && State != EHCPState::Shove; }
	bool CanAct() const { return State == EHCPState::Free && ActionLock <= 0.f; }
	bool IsShooting() const { return State == EHCPState::ShootWindup || State == EHCPState::ShootAir || State == EHCPState::Layup; }
	bool IsDunking() const { return State == EHCPState::DunkWindup || State == EHCPState::DunkAir || State == EHCPState::DunkHang; }
	FVector FeetLocation() const;
	FVector BoneLocation(FName Bone) const;
	FVector HandsCenter() const;
	FVector BallHoldPoint() const;
	EHCBallHold GetBallHold() const;
	/** Where the ball should be while dribbling given the anim phase; returns normalized dribble phase. */
	float GetDribblePhase() const;
	float DunkRange() const;
	float MaxSpeed() const;
	int32 AttackHoop() const;
	FVector2D Planar() const { const FVector L = GetActorLocation(); return FVector2D(L.X, L.Y); }

	// --- actions -------------------------------------------------------------
	void StartJumpShot();
	void StartLayup();
	void StartDunk(bool bAlleyOop = false);
	void StartPass(AHCCharacter* Target, bool bAlley);
	void StartShove(AHCCharacter* Target);
	void StartSteal();
	void StartBlock();
	void TakeShove(const FVector& Dir, float Speed, bool bKnockDown);
	void Celebrate();
	void SetInbound(bool bOn);
	void ResetForPlay();
	/** Force the AI/teammate to release a shot now (human held/queued release). */
	void ReleaseShot();
	void OnCaughtBall();
	void SetFire(bool bFire);
	void PlayAnim(EHCAnim A, bool bLoop, float Rate = 1.f, float Blend = 0.15f, float Start = 0.f, bool bRestart = false);

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> HairMesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> BeardMesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> HeadbandMesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> WristMesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> NumMeshA;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> NumMeshB;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> TextMesh;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Ring;
	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UHCSpriteFX> FX;

	// dunk flight
	FVector DunkStart = FVector::ZeroVector;
	FVector DunkEnd = FVector::ZeroVector;
	float DunkDuration = 1.f;
	float DunkApex = 100.f;
	EHCDunkStyle DunkStyle = EHCDunkStyle::TwoHand;
	bool bAlleyDunk = false;
	bool bDunkBlocked = false;
	bool bBlockAttempted = false;
	FRotator DunkBaseRot = FRotator::ZeroRotator;

	// shot timing
	float LaunchTime = 0.f;
	float ApexTime = 0.f;
	bool bReleaseQueued = false;
	bool bTapShot = false;      // quick tap: auto-release just before the apex
	bool bShotReleased = false;
	float ReleaseQuality = 0.f;

	// pass / shove target
	UPROPERTY(Transient)
	TObjectPtr<AHCCharacter> ActionTarget = nullptr;
	bool bActionAlley = false;
	bool bActionDone = false;
	bool bPowerShove = false;

private:
	AHCGameMode* GM() const;
	void TickState(float Dt);
	void TickMovement(float Dt);
	void DropFromDunk();
	void TickLocomotionAnim(float Dt);
	void TickFacing(float Dt);
	void TickTurbo(float Dt);
	void TickFX(float Dt);
	void HandleActionInput();
	AHCCharacter* FindShoveOpponent(const FVector& Facing, float Reach) const;
	void SetState(EHCPState S);
	void FaceTowards(const FVector& P, float Dt, float Speed = 14.f);
	void SetPartMesh(USkeletalMeshComponent* C, const TCHAR* Name);
	void ApplyColors(const FHCTeamDef& TeamDef);

	UPROPERTY(Transient)
	TObjectPtr<UHCAnimInstance> Anim = nullptr;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UMaterialInstanceDynamic>> BodyMIDs;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> RingMID;
	EHCAnim CurAnim = EHCAnim::Count;
	float DesiredYaw = 0.f;
	bool bGuardingBall = false;
	bool bWasAirborne = false;
	float FireFXAccum = 0.f;
	float SqueakCooldown = 0.f;
};
