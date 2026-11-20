#include "HCCharacter.h"
#include "HeatCheck.h"
#include "HCAnimInstance.h"
#include "HCGameMode.h"
#include "HCBall.h"
#include "HCHoop.h"
#include "HCSpriteFX.h"
#include "HCAudio.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Animation/AnimSequence.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"
#include "Kismet/GameplayStatics.h"

namespace
{
	const TCHAR* GAnimNames[] = {
		TEXT("A_Idle"), TEXT("A_Defense"), TEXT("A_DribbleIdle"), TEXT("A_Run"), TEXT("A_Sprint"), TEXT("A_RunDribble"),
		TEXT("A_HoldBall"), TEXT("A_JumpShot"), TEXT("A_Layup"), TEXT("A_Dunk"), TEXT("A_DunkWindmill"), TEXT("A_Pass"),
		TEXT("A_Shove"), TEXT("A_Steal"), TEXT("A_Block"), TEXT("A_Fall"), TEXT("A_GetUp"), TEXT("A_Celebrate"),
		TEXT("A_ShuffleLeft"), TEXT("A_ShuffleRight"), TEXT("A_Backpedal"), TEXT("A_Land"), TEXT("A_Tip") };
	static_assert(UE_ARRAY_COUNT(GAnimNames) == (int32)EHCAnim::Count, "anim table");

	UAnimSequence* GetAnimAsset(EHCAnim A)
	{
		static UAnimSequence* Cache[(int32)EHCAnim::Count] = {};
		const int32 I = (int32)A;
		if (!Cache[I])
		{
			const FString Path = FString::Printf(TEXT("/Game/HeatCheck/Anims/%s.%s"), GAnimNames[I], GAnimNames[I]);
			Cache[I] = LoadObject<UAnimSequence>(nullptr, *Path);
			if (Cache[I])
			{
				Cache[I]->AddToRoot();
			}
			else
			{
				UE_LOG(LogHeatCheck, Warning, TEXT("Missing animation %s"), *Path);
			}
		}
		return Cache[I];
	}

	bool IsDribbleAnim(EHCAnim A) { return A == EHCAnim::DribbleIdle || A == EHCAnim::RunDribble; }

	constexpr float JumpShotSetTime = 13.f / 30.f;
	constexpr float JumpShotReleaseTime = 16.f / 30.f;
	constexpr float DunkSlamTime = 24.f / 30.f;
	bool IsGuardStep(EHCAnim A)
	{
		return A == EHCAnim::ShuffleLeft || A == EHCAnim::ShuffleRight || A == EHCAnim::Backpedal;
	}

	bool IsStride(EHCAnim A)
	{
		return A == EHCAnim::Run || A == EHCAnim::Sprint || A == EHCAnim::RunDribble || IsGuardStep(A);
	}
}

AHCCharacter::AHCCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessAI = EAutoPossessAI::Disabled;
	AIControllerClass = nullptr;
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;

	GetCapsuleComponent()->InitCapsuleSize(HC::PlayerRadius, HC::PlayerHalfHeight);
	GetCapsuleComponent()->SetCollisionProfileName(TEXT("Pawn"));
	GetCapsuleComponent()->CanCharacterStepUpOn = ECB_No;

	UCharacterMovementComponent* M = GetCharacterMovement();
	M->bOrientRotationToMovement = false;
	M->bRunPhysicsWithNoController = true;
	M->MaxWalkSpeed = 600.f;
	M->MaxAcceleration = 3400.f;
	M->BrakingDecelerationWalking = 3800.f;
	M->GroundFriction = 9.f;
	M->GravityScale = 2.0f;
	M->AirControl = 0.15f;
	M->JumpZVelocity = 600.f;
	M->bCanWalkOffLedges = true;
	M->MaxStepHeight = 20.f;

	USkeletalMeshComponent* Body = GetMesh();
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> BodyAsset(TEXT("/Game/HeatCheck/Characters/SK_Player.SK_Player"));
	if (BodyAsset.Succeeded())
	{
		Body->SetSkeletalMeshAsset(BodyAsset.Object);
	}
	Body->SetRelativeLocation(FVector(0.f, 0.f, -HC::PlayerHalfHeight));
	Body->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	Body->SetAnimationMode(EAnimationMode::AnimationBlueprint);
	Body->SetAnimInstanceClass(UHCAnimInstance::StaticClass());
	Body->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->bCastDynamicShadow = true;

	auto MakePart = [this, Body](FName Name) -> USkeletalMeshComponent*
	{
		USkeletalMeshComponent* C = CreateDefaultSubobject<USkeletalMeshComponent>(Name);
		C->SetupAttachment(Body);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetGenerateOverlapEvents(false);
		// leader-pose followers don't invalidate cached virtual shadow pages, which leaves stale
		// shadow specks on the floor; the body's own shadow is plenty
		C->SetCastShadow(false);
		return C;
	};
	HairMesh = MakePart(TEXT("Hair"));
	BeardMesh = MakePart(TEXT("Beard"));
	HeadbandMesh = MakePart(TEXT("Headband"));
	WristMesh = MakePart(TEXT("Wrist"));
	NumMeshA = MakePart(TEXT("NumA"));
	NumMeshB = MakePart(TEXT("NumB"));
	TextMesh = MakePart(TEXT("JerseyText"));

	Ring = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Ring"));
	Ring->SetupAttachment(GetCapsuleComponent());
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Plane(TEXT("/Engine/BasicShapes/Plane.Plane"));
	if (Plane.Succeeded())
	{
		Ring->SetStaticMesh(Plane.Object);
	}
	Ring->SetUsingAbsoluteRotation(true);
	Ring->SetRelativeLocation(FVector(0.f, 0.f, -HC::PlayerHalfHeight + 1.5f));
	Ring->SetRelativeScale3D(FVector(1.55f, 1.55f, 1.f));
	Ring->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Ring->SetCastShadow(false);
	Ring->bAffectDistanceFieldLighting = false;
	Ring->bAffectDynamicIndirectLighting = false;
	Ring->bVisibleInReflectionCaptures = false;
	Ring->bVisibleInRayTracing = false;

	FX = CreateDefaultSubobject<UHCSpriteFX>(TEXT("FX"));
	FX->SetupAttachment(GetCapsuleComponent());
}

AHCGameMode* AHCCharacter::GM() const
{
	return Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this));
}

void AHCCharacter::SetPartMesh(USkeletalMeshComponent* C, const TCHAR* Name)
{
	if (!Name)
	{
		C->SetSkeletalMeshAsset(nullptr);
		C->SetVisibility(false);
		return;
	}
	const FString Path = FString::Printf(TEXT("/Game/HeatCheck/Characters/%s.%s"), Name, Name);
	USkeletalMesh* SK = LoadObject<USkeletalMesh>(nullptr, *Path);
	C->SetSkeletalMeshAsset(SK);
	C->SetVisibility(SK != nullptr);
	if (SK)
	{
		C->SetLeaderPoseComponent(GetMesh(), true);
	}
}

void AHCCharacter::Setup(int32 InTeam, int32 InSlot, const FHCTeamDef& TeamDef, const FHCPlayerDef& InDef)
{
	// Warm the shared animation cache before the first possession.
	for (int32 i = 0; i < UE_ARRAY_COUNT(GAnimNames); ++i)
	{
		GetAnimAsset(static_cast<EHCAnim>(i));
	}
	Team = InTeam;
	Slot = InSlot;
	Def = InDef;
	TeamColor = TeamDef.Primary;
	Stats = FHCStats();
	Streak = 0;
	bOnFire = false;
	FireMakes = 0;
	Turbo = 1.f;

	if (!Anim)
	{
		Anim = Cast<UHCAnimInstance>(GetMesh()->GetAnimInstance());
	}
	if (!FX->NumAlive() && FX->GetInstanceCount() == 0)
	{
		FX->InitPool(140, LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/HeatCheck/Materials/MI_FXFire.MI_FXFire")));
	}

	const TCHAR* HairNames[] = { nullptr, TEXT("SK_Hair_Buzz"), TEXT("SK_Hair_Flattop"), TEXT("SK_Hair_Afro"), TEXT("SK_Hair_Braids"),
		TEXT("SK_Hair_Mohawk"), TEXT("SK_Hair_Curls"), TEXT("SK_Hair_Bun") };
	SetPartMesh(HairMesh, HairNames[(int32)Def.Hair]);
	SetPartMesh(BeardMesh, Def.Beard == EHCBeard::Full ? TEXT("SK_Beard_Full") : Def.Beard == EHCBeard::Goatee ? TEXT("SK_Beard_Goatee") : nullptr);
	SetPartMesh(HeadbandMesh, Def.bHeadband ? TEXT("SK_Headband") : nullptr);
	SetPartMesh(WristMesh, Def.bWristbands ? TEXT("SK_Wristbands") : nullptr);
	const int32 N = FMath::Clamp(Def.Number, 0, 99);
	if (N >= 10)
	{
		SetPartMesh(NumMeshA, *FString::Printf(TEXT("SK_Num_T%d"), N / 10));
		SetPartMesh(NumMeshB, *FString::Printf(TEXT("SK_Num_O%d"), N % 10));
	}
	else
	{
		SetPartMesh(NumMeshA, *FString::Printf(TEXT("SK_Num_C%d"), N));
		SetPartMesh(NumMeshB, nullptr);
	}
	SetPartMesh(TextMesh, *FString::Printf(TEXT("SK_JerseyText_%s"), *TeamDef.Abbr));

	GetMesh()->SetRelativeScale3D(FVector(Def.Build, Def.Build, Def.Height));
	ApplyColors(TeamDef);
	ResetForPlay();
}

void AHCCharacter::ApplyHeadScale(float S)
{
	if (!Anim)
	{
		Anim = Cast<UHCAnimInstance>(GetMesh()->GetAnimInstance());
	}
	if (Anim)
	{
		Anim->HeadScale = S;
	}
}

void AHCCharacter::ApplyColors(const FHCTeamDef& TD)
{
	BodyMIDs.Reset();
	const FLinearColor White(0.92f, 0.92f, 0.92f);
	auto ColorFor = [&](const FString& SlotName) -> TOptional<FLinearColor>
	{
		if (SlotName == TEXT("MI_PlayerSkin")) return Def.Skin;
		if (SlotName == TEXT("MI_PlayerJersey") || SlotName == TEXT("MI_PlayerShorts")) return TD.Primary;
		if (SlotName == TEXT("MI_PlayerJerseyTrim") || SlotName == TEXT("MI_PlayerShortsTrim")) return TD.Secondary;
		if (SlotName == TEXT("MI_PlayerSocks")) return White;
		if (SlotName == TEXT("MI_PlayerShoe")) return TD.Secondary;
		if (SlotName == TEXT("MI_PlayerShoeAccent")) return TD.Primary;
		if (SlotName == TEXT("MI_PlayerShoeSole")) return White;
		if (SlotName == TEXT("MI_PlayerHair")) return Def.HairColor;
		if (SlotName == TEXT("MI_PlayerAccessory")) return TD.Accent;
		if (SlotName == TEXT("MI_PlayerNumber") || SlotName == TEXT("MI_PlayerJerseyText")) return TD.Secondary;
		return TOptional<FLinearColor>();
	};
	TArray<UMeshComponent*> Comps = { GetMesh(), HairMesh, BeardMesh, HeadbandMesh, WristMesh, NumMeshA, NumMeshB, TextMesh };
	for (UMeshComponent* C : Comps)
	{
		if (!C || !C->IsVisible())
		{
			continue;
		}
		const TArray<FName> Slots = C->GetMaterialSlotNames();
		for (int32 i = 0; i < C->GetNumMaterials(); ++i)
		{
			UMaterialInstanceDynamic* MID = C->CreateDynamicMaterialInstance(i);
			if (!MID)
			{
				continue;
			}
			const FString SlotName = Slots.IsValidIndex(i) ? Slots[i].ToString() : FString();
			if (const TOptional<FLinearColor> Col = ColorFor(SlotName))
			{
				MID->SetVectorParameterValue(TEXT("BaseColor"), Col.GetValue());
			}
			BodyMIDs.Add(MID);
		}
	}
	if (UMaterialInterface* RingMat = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/HeatCheck/Materials/MI_PlayerRing.MI_PlayerRing")))
	{
		RingMID = UMaterialInstanceDynamic::Create(RingMat, this);
		Ring->SetMaterial(0, RingMID);
	}
	SetFire(bOnFire);
}

void AHCCharacter::SetFire(bool bFire)
{
	bOnFire = bFire;
	for (UMaterialInstanceDynamic* MID : BodyMIDs)
	{
		if (MID)
		{
			MID->SetScalarParameterValue(TEXT("RimStrength"), bFire ? 3.0f : 0.f);
			MID->SetVectorParameterValue(TEXT("RimColor"), FLinearColor(1.f, 0.42f, 0.05f));
		}
	}
}

void AHCCharacter::ResetForPlay()
{
	State = EHCPState::Free;
	StateTime = 0.f;
	ActionLock = 0.f;
	bAlleyDunk = false;
	bDunkBlocked = false;
	Input = FHCInput();
	GetCharacterMovement()->SetMovementMode(MOVE_Walking);
	GetMesh()->SetRelativeLocation(FVector(0.f, 0.f, -HC::PlayerHalfHeight));
	GetMesh()->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	PlayAnim(EHCAnim::Idle, true, 1.f, 0.1f);
}

// -----------------------------------------------------------------------------
// queries
// -----------------------------------------------------------------------------

bool AHCCharacter::HasBall() const
{
	const AHCGameMode* G = GM();
	return G && G->Ball && G->Ball->GetHolder() == this;
}

bool AHCCharacter::IsAirborne() const
{
	return GetCharacterMovement()->IsFalling() || IsDunking();
}

FVector AHCCharacter::FeetLocation() const
{
	return GetActorLocation() - FVector(0.f, 0.f, HC::PlayerHalfHeight);
}

FVector AHCCharacter::BoneLocation(FName Bone) const
{
	return GetMesh()->GetSocketLocation(Bone);
}

FVector AHCCharacter::HandsCenter() const
{
	return (BoneLocation(TEXT("grip_l")) + BoneLocation(TEXT("grip_r"))) * 0.5f;
}

EHCBallHold AHCCharacter::GetBallHold() const
{
	switch (State)
	{
	case EHCPState::ShootWindup:
	case EHCPState::ShootAir:
	case EHCPState::Pass:
	case EHCPState::Inbound:
		return EHCBallHold::TwoHands;
	case EHCPState::Layup:
		return StateTime < 0.22f ? EHCBallHold::TwoHands : EHCBallHold::RightHand;
	case EHCPState::DunkWindup:
	case EHCPState::DunkAir:
	case EHCPState::DunkHang:
		if (DunkStyle == EHCDunkStyle::Windmill && State == EHCPState::DunkAir)
		{
			return EHCBallHold::RightHand;
		}
		return EHCBallHold::TwoHands;
	default:
		break;
	}
	if (CurAnim == EHCAnim::HoldBall)
	{
		return EHCBallHold::TwoHands;
	}
	return EHCBallHold::Dribble;
}

FVector AHCCharacter::BallHoldPoint() const
{
	switch (GetBallHold())
	{
	case EHCBallHold::TwoHands: return HandsCenter();
	case EHCBallHold::RightHand: return BoneLocation(TEXT("grip_r"));
	default: return BoneLocation(TEXT("grip_r"));
	}
}

float AHCCharacter::GetDribblePhase() const
{
	if (Anim && IsDribbleAnim(CurAnim))
	{
		return FMath::Frac(Anim->GetNormalizedTime());
	}
	return FMath::Frac(GetWorld()->GetTimeSeconds() * 1.8f);
}

float AHCCharacter::DunkRange() const
{
	return 430.f + Def.Dunk * 30.f + (bOnFire ? 120.f : 0.f);
}

float AHCCharacter::MaxSpeed() const
{
	float S = 505.f + Def.Speed * 14.f;
	if (HasBall())
	{
		S *= 0.94f;
	}
	if (Input.bTurbo && (Turbo > 0.02f || bOnFire))
	{
		S *= 1.40f;
	}
	return S;
}

int32 AHCCharacter::AttackHoop() const
{
	const AHCGameMode* G = GM();
	return G ? G->AttackHoop(Team) : 1;
}

void AHCCharacter::PlayAnim(EHCAnim A, bool bLoop, float Rate, float Blend, float Start, bool bRestart)
{
	if (!Anim)
	{
		Anim = Cast<UHCAnimInstance>(GetMesh()->GetAnimInstance());
		if (!Anim)
		{
			return;
		}
	}
	UAnimSequence* Seq = GetAnimAsset(A);
	if (!Seq)
	{
		return;
	}
	if (!bRestart && A != CurAnim && ((IsDribbleAnim(A) && IsDribbleAnim(CurAnim)) || (IsStride(A) && IsStride(CurAnim))))
	{
		// Preserve the supporting foot and bounce phase across compatible loops.
		Start = FMath::Frac(Anim->GetNormalizedTime()) * Seq->GetPlayLength();
	}
	Anim->Play(Seq, bLoop, Rate, Blend, Start, bRestart);
	CurAnim = A;
}

// -----------------------------------------------------------------------------
// actions
// -----------------------------------------------------------------------------

void AHCCharacter::SetState(EHCPState S)
{
	State = S;
	StateTime = 0.f;
	bActionDone = false;
}

void AHCCharacter::FaceTowards(const FVector& P, float Dt, float Speed)
{
	const FVector D = P - GetActorLocation();
	if (D.SizeSquared2D() > 1.f)
	{
		DesiredYaw = D.Rotation().Yaw;
	}
}

void AHCCharacter::StartJumpShot()
{
	SetState(EHCPState::ShootWindup);
	bShotReleased = false;
	bReleaseQueued = false;
	bTapShot = false;
	PlayAnim(EHCAnim::JumpShot, false, 1.f, 0.08f, 0.f, true);
	FaceTowards(GM()->RimCenter(AttackHoop()), 0.f);
	UCharacterMovementComponent* M = GetCharacterMovement();
	M->Velocity *= 0.3f;
}

void AHCCharacter::StartLayup()
{
	SetState(EHCPState::Layup);
	bShotReleased = false;
	PlayAnim(EHCAnim::Layup, false, 1.1f, 0.06f, 0.f, true);
	FaceTowards(GM()->RimCenter(AttackHoop()), 0.f);
}

void AHCCharacter::StartDunk(bool bAlleyOop)
{
	AHCGameMode* G = GM();
	SetState(EHCPState::DunkWindup);
	bAlleyDunk = bAlleyOop;
	bDunkBlocked = false;
	const FVector Rim = G->RimCenter(AttackHoop());
	const float Dist = FVector::Dist2D(GetActorLocation(), Rim);
	const float R = FMath::FRand();
	if (bOnFire && Dist > 300.f)
	{
		DunkStyle = EHCDunkStyle::Flip;
	}
	else if (Dist < 260.f)
	{
		DunkStyle = R < 0.75f ? EHCDunkStyle::TwoHand : EHCDunkStyle::Windmill;
	}
	else if (Dist < 450.f)
	{
		DunkStyle = R < 0.4f ? EHCDunkStyle::Windmill : (R < 0.75f ? EHCDunkStyle::Spin360 : EHCDunkStyle::TwoHand);
	}
	else
	{
		DunkStyle = R < 0.4f ? EHCDunkStyle::Spin360 : (R < 0.75f ? EHCDunkStyle::Windmill : EHCDunkStyle::Reverse);
	}
	if (bAlleyOop)
	{
		DunkStyle = R < 0.5f ? EHCDunkStyle::TwoHand : EHCDunkStyle::Spin360;
	}
	PlayAnim(DunkStyle == EHCDunkStyle::Windmill ? EHCAnim::DunkWindmill : EHCAnim::Dunk, false, 1.f, 0.06f, 0.f, true);
	FaceTowards(Rim, 0.f);
	if (!bOnFire)
	{
		Turbo = FMath::Max(0.f, Turbo - 0.12f);
	}
}

void AHCCharacter::StartPass(AHCCharacter* Target, bool bAlley)
{
	SetState(EHCPState::Pass);
	ActionTarget = Target;
	bActionAlley = bAlley;
	PlayAnim(EHCAnim::Pass, false, 1.35f, 0.06f, 0.f, true);
	if (Target)
	{
		FaceTowards(Target->GetActorLocation(), 0.f);
	}
}

AHCCharacter* AHCCharacter::FindShoveOpponent(const FVector& Facing, float Reach) const
{
	AHCCharacter* Best = nullptr;
	float BestScore = MAX_flt;
	for (AHCCharacter* Opponent : GM()->Players)
	{
		if (Opponent->Team == Team || Opponent->IsDown() || Opponent->State == EHCPState::Stagger
			|| Opponent->State == EHCPState::DunkAir || Opponent->State == EHCPState::DunkHang)
		{
			continue;
		}
		const FVector Delta = Opponent->GetActorLocation() - GetActorLocation();
		const float Distance = Delta.Size2D();
		const float Alignment = FVector::DotProduct(Facing, Delta.GetSafeNormal2D());
		const float Score = Distance - Alignment * 50.f;
		if (Distance <= Reach && FMath::Abs(Delta.Z) <= 64.f && Alignment >= 0.4f && Score < BestScore)
		{
			Best = Opponent;
			BestScore = Score;
		}
	}
	return Best;
}

void AHCCharacter::StartShove(AHCCharacter* Target)
{
	if (!CanAct() || IsAirborne() || HasBall() || ShoveCooldown > 0.f || GM()->Phase != EHCPhase::Live)
	{
		return;
	}
	const FVector Aim = Input.Move.IsNearlyZero() ? GetActorForwardVector() : FVector(Input.Move, 0.f).GetSafeNormal2D();
	if (!Target)
	{
		Target = FindShoveOpponent(Aim, 155.f);
	}
	const FVector Dir = Target ? (Target->GetActorLocation() - GetActorLocation()).GetSafeNormal2D() : Aim;
	bPowerShove = bOnFire || (Input.bTurbo && Turbo >= 0.2f);
	SetState(EHCPState::Shove);
	ShoveCooldown = 0.9f;
	if (bPowerShove && !bOnFire)
	{
		Turbo = FMath::Max(0.f, Turbo - 0.2f);
	}
	PlayAnim(EHCAnim::Shove, false, 1.25f, 0.05f, 0.f, true);
	FaceTowards(GetActorLocation() + Dir * 100.f, 0.f);
	GetCharacterMovement()->Velocity = Dir * 450.f;
}

void AHCCharacter::StartSteal()
{
	SetState(EHCPState::Steal);
	StealCooldown = 0.55f;
	PlayAnim(EHCAnim::Steal, false, 1.3f, 0.05f, 0.f, true);
	if (AHCGameMode* G = GM())
	{
		if (G->Ball && G->Ball->GetHolder())
		{
			FaceTowards(G->Ball->GetHolder()->GetActorLocation(), 0.f);
		}
	}
}

void AHCCharacter::StartBlock()
{
	bBlockAttempted = false;
	SetState(EHCPState::Block);
	PlayAnim(GM()->Phase == EHCPhase::TipOff ? EHCAnim::Tip : EHCAnim::Block, false, 1.f, 0.05f, 0.f, true);
}

void AHCCharacter::TakeShove(const FVector& Dir, float Speed, bool bKnockDown)
{
	if (IsDunking())
	{
		GetMesh()->SetRelativeLocation(FVector(0.f, 0.f, -HC::PlayerHalfHeight));
		GetMesh()->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	}
	SetState(bKnockDown ? EHCPState::KnockedDown : EHCPState::Stagger);
	GetCharacterMovement()->SetMovementMode(MOVE_Falling);
	DesiredYaw = (-Dir).Rotation().Yaw;
	SetActorRotation(FRotator(0.f, DesiredYaw, 0.f));
	LaunchCharacter(Dir * Speed + FVector(0, 0, bKnockDown ? 220.f : 95.f), true, true);
	PlayAnim(bKnockDown ? EHCAnim::Fall : EHCAnim::Backpedal, !bKnockDown, 1.f, 0.05f, 0.f, true);
}

void AHCCharacter::Celebrate()
{
	if (State == EHCPState::Free)
	{
		SetState(EHCPState::Celebrate);
		PlayAnim(EHCAnim::Celebrate, false, 1.f, 0.1f, 0.f, true);
	}
}

void AHCCharacter::SetInbound(bool bOn)
{
	if (bOn)
	{
		SetState(EHCPState::Inbound);
		PlayAnim(EHCAnim::HoldBall, true, 1.f, 0.1f);
	}
	else if (State == EHCPState::Inbound)
	{
		SetState(EHCPState::Free);
	}
}

void AHCCharacter::ReleaseShot()
{
	if (State == EHCPState::ShootAir && !bShotReleased)
	{
		bShotReleased = true;
		const float Now = GetWorld()->GetTimeSeconds();
		const float Off = FMath::Abs(Now - ApexTime);
		ReleaseQuality = 1.f - FMath::Clamp(Off / 0.24f, 0.f, 1.f);
		if (Anim)
		{
			// Keep button release immediate while carrying the current pose into the wrist snap.
			Anim->SetRate(FMath::Clamp((JumpShotReleaseTime - Anim->GetTime()) / 0.065f, 1.f, 3.f));
		}
		if (AHCGameMode* G = GM())
		{
			G->ReleaseShot(this, ReleaseQuality, false);
		}
	}
	else if (State == EHCPState::ShootWindup)
	{
		bReleaseQueued = true;
	}
}

void AHCCharacter::OnCaughtBall()
{
	ActionLock = 0.1f;
}

// -----------------------------------------------------------------------------
// tick
// -----------------------------------------------------------------------------

void AHCCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	AHCGameMode* G = GM();
	if (!G)
	{
		return;
	}
	const float Dt = DeltaSeconds;
	StateTime += Dt;
	ActionLock -= Dt;
	StealCooldown -= Dt;
	ShoveCooldown -= Dt;
	SqueakCooldown -= Dt;

	if (State == EHCPState::Free && G->IsPlayLive())
	{
		HandleActionInput();
	}
	else if (State == EHCPState::Inbound && Input.bPassPressed && G->IsPlayLive())
	{
		if (AHCCharacter* Mate = G->Teammate(this))
		{
			StartPass(Mate, false);
		}
	}
	TickState(Dt);
	TickMovement(Dt);
	TickTurbo(Dt);
	TickFacing(Dt);
	if (State == EHCPState::Free)
	{
		TickLocomotionAnim(Dt);
	}
	TickFX(Dt);

	// keep everyone on the floor area (inbounders may stand just out of bounds)
	if (State != EHCPState::Inbound && !IsDunking())
	{
		FVector L = GetActorLocation();
		const float MX = HC::CourtHalfLength + HC::BoundsMargin;
		const float MY = HC::CourtHalfWidth + HC::BoundsMargin;
		if (FMath::Abs(L.X) > MX || FMath::Abs(L.Y) > MY)
		{
			L.X = FMath::Clamp(L.X, -MX, MX);
			L.Y = FMath::Clamp(L.Y, -MY, MY);
			SetActorLocation(L);
		}
	}
	Input.ClearEdges();
}

void AHCCharacter::HandleActionInput()
{
	if (!CanAct())
	{
		return;
	}
	AHCGameMode* G = GM();
	AHCBall* B = G->Ball;
	AHCCharacter* Mate = G->Teammate(this);
	const bool bTurboOK = Input.bTurbo && (Turbo > 0.05f || bOnFire);

	if (G->Phase == EHCPhase::TipOff)
	{
		if (Input.bShootPressed && !IsAirborne() && G->TipJumpers[Team].Get() == this && B->GetState() == EHCBallState::Loose)
		{
			StartBlock();
		}
		return;
	}

	if (HasBall())
	{
		if (Input.bShootPressed)
		{
			const float D = G->DistToHoop(GetActorLocation(), AttackHoop());
			if (bTurboOK && D < DunkRange())
			{
				StartDunk(false);
			}
			else if (D < 200.f)
			{
				if (Def.Dunk >= 7 && Input.bTurbo)
				{
					StartDunk(false);
				}
				else
				{
					StartLayup();
				}
			}
			else
			{
				StartJumpShot();
			}
		}
		else if (Input.bPassPressed && Mate && !Mate->IsDown())
		{
			const bool bAlley = Input.bTurbo && Mate->CanAct() && !Mate->HasBall()
				&& G->DistToHoop(Mate->GetActorLocation(), AttackHoop()) < Mate->DunkRange() + 60.f;
			StartPass(Mate, bAlley);
		}
		return;
	}

	AHCCharacter* Holder = B ? B->GetHolder() : nullptr;
	const bool bMateHas = Holder && Holder == Mate;
	if (Input.bShovePressed || (Input.bPassPressed && Input.bTurbo && !bMateHas))
	{
		StartShove(nullptr);
		return;
	}
	if (Input.bPassPressed)
	{
		if (bMateHas)
		{
			G->RequestPass(Mate, this);
		}
		else if (StealCooldown <= 0.f)
		{
			StartSteal();
		}
	}
	if (Input.bShootPressed && State == EHCPState::Free)
	{
		if (bMateHas)
		{
			G->RequestShot(Mate);
		}
		else if (!IsAirborne())
		{
			StartBlock();
		}
	}
}

void AHCCharacter::TickState(float Dt)
{
	AHCGameMode* G = GM();
	UCharacterMovementComponent* M = GetCharacterMovement();
	switch (State)
	{
	case EHCPState::Free:
		break;

	case EHCPState::ShootWindup:
		if (!Input.bShootDown)
		{
			bReleaseQueued = true;
			if (StateTime < 0.12f)
			{
				bTapShot = true;
			}
		}
		if (StateTime >= 0.2f)
		{
			const float Vz = 560.f;
			LaunchCharacter(FVector(M->Velocity.X * 0.25f, M->Velocity.Y * 0.25f, Vz), true, true);
			LaunchTime = GetWorld()->GetTimeSeconds();
			ApexTime = LaunchTime + Vz / (HC::Gravity * M->GravityScale);
			SetState(EHCPState::ShootAir);
			G->OnJump(this);
		}
		break;

	case EHCPState::ShootAir:
		if (bShotReleased && Anim && Anim->GetTime() >= JumpShotReleaseTime)
		{
			Anim->SetRate(1.f);
		}
		if (!bShotReleased)
		{
			if (Anim && Anim->GetTime() >= JumpShotSetTime)
			{
				Anim->SetRate(0.f);
			}
			const float Now = GetWorld()->GetTimeSeconds();
			const bool bWantsRelease = bTapShot ? (Now >= ApexTime - 0.035f)
				: (!Input.bShootDown || (bReleaseQueued && Now - LaunchTime > 0.08f));
			const bool bLate = M->Velocity.Z < -380.f;
			if ((bWantsRelease && StateTime > 0.06f) || bLate)
			{
				ReleaseShot();
			}
		}
		if (StateTime > 0.15f && !M->IsFalling())
		{
			if (!bShotReleased)
			{
				ReleaseShot();
			}
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Layup:
		if (StateTime >= 0.1f && !bActionDone)
		{
			bActionDone = true;
			const FVector Rim = G->RimCenter(AttackHoop());
			const FVector Dir = (Rim - GetActorLocation()).GetSafeNormal2D();
			const float D = FVector::Dist2D(Rim, GetActorLocation());
			LaunchCharacter(Dir * FMath::Clamp(D * 1.4f, 80.f, 320.f) + FVector(0, 0, 560.f), true, true);
			G->OnJump(this);
		}
		if (StateTime >= 0.36f && !bShotReleased)
		{
			bShotReleased = true;
			G->ReleaseShot(this, 0.85f, true);
		}
		if (StateTime > 0.3f && !M->IsFalling())
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::DunkWindup:
	{
		const float Windup = bAlleyDunk ? 0.05f : 0.14f;
		if (StateTime >= Windup)
		{
			const FVector Rim = G->RimCenter(AttackHoop());
			DunkStart = GetActorLocation();
			FVector Approach = (Rim - DunkStart).GetSafeNormal2D();
			if (Approach.IsNearlyZero())
			{
				Approach = -G->Hoops[AttackHoop()]->Facing();
			}
			const float Dist = FVector::Dist2D(Rim, DunkStart);
			// A reverse finishes on the far side, looking back toward the rim.
			DunkEnd = Rim + Approach * (DunkStyle == EHCDunkStyle::Reverse ? 46.f : -46.f);
			DunkEnd.Z = HC::RimZ + 18.f - 158.f * Def.Height + HC::PlayerHalfHeight;
			DunkDuration = FMath::Clamp(0.48f + Dist / 950.f, 0.55f, 1.15f);
			if (bAlleyDunk && G->Ball && G->Ball->GetState() == EHCBallState::Pass)
			{
				DunkDuration = FMath::Max(DunkDuration, G->Ball->RemainingPassTime() + 0.14f);
			}
			DunkApex = 50.f + Dist * 0.07f;
			DunkBaseRot = FRotator(0.f, Approach.Rotation().Yaw, 0.f);
			M->SetMovementMode(MOVE_Flying);
			M->StopMovementImmediately();
			SetState(EHCPState::DunkAir);
			G->DunkTakeoff(this);
		}
		break;
	}

	case EHCPState::DunkAir:
	{
		const bool bLobInFlight = bAlleyDunk && G->Ball->GetState() == EHCBallState::Pass && G->Ball->GetPassTarget() == this;
		if (bDunkBlocked || (!HasBall() && !bLobInFlight))
		{
			DropFromDunk();
			break;
		}
		const float T = FMath::Clamp(StateTime / DunkDuration, 0.f, 1.f);
		const float Ease = T * T * (3.f - 2.f * T) * 0.35f + T * 0.65f;
		FVector P = FMath::Lerp(DunkStart, DunkEnd, Ease);
		P.Z = FMath::Lerp(DunkStart.Z, DunkEnd.Z, T) + DunkApex * 4.f * T * (1.f - T);
		SetActorLocation(P, false);
		// style rotations
		float Yaw = DunkBaseRot.Yaw;
		FQuat MeshQ = FQuat(FRotator(0.f, -90.f, 0.f));
		FVector MeshLoc(0.f, 0.f, -HC::PlayerHalfHeight);
		const float S = FMath::SmoothStep(0.05f, 0.85f, T);
		if (DunkStyle == EHCDunkStyle::Spin360)
		{
			Yaw += 360.f * S;
		}
		else if (DunkStyle == EHCDunkStyle::Reverse)
		{
			Yaw += 180.f * S;
		}
		else if (DunkStyle == EHCDunkStyle::Flip)
		{
			const FQuat Flip(FVector(0.f, 1.f, 0.f), FMath::DegreesToRadians(-360.f * S));
			MeshQ = Flip * MeshQ;
			MeshLoc = Flip.RotateVector(MeshLoc);
		}
		SetActorRotation(FRotator(0.f, Yaw, 0.f));
		DesiredYaw = Yaw;
		GetMesh()->SetRelativeLocationAndRotation(MeshLoc, MeshQ);
		if (Anim)
		{
			Anim->SetRate(0.f);
			// Pick up the gather exactly where takeoff interrupted it.
			const float TakeoffTime = bAlleyDunk ? 0.05f : 0.14f;
			Anim->SetTime(FMath::Lerp(TakeoffTime, DunkSlamTime, T));
		}
		if (T >= 1.f)
		{
			GetMesh()->SetRelativeLocationAndRotation(FVector(0.f, 0.f, -HC::PlayerHalfHeight), FRotator(0.f, -90.f, 0.f));
			SetState(EHCPState::DunkHang);
			if (Anim)
			{
				Anim->SetTime(DunkSlamTime);
				Anim->SetRate(1.f);
			}
			const bool bHadBall = HasBall();
			G->DunkSlam(this);
			if (!bHadBall || bDunkBlocked)
			{
				DropFromDunk();
			}
		}
		break;
	}

	case EHCPState::DunkHang:
	{
		// Follow the swinging pose with the body so the hands stay on the near rim.
		const FVector Anchor = G->RimCenter(AttackHoop()) - GetActorForwardVector() * 16.f;
		const FVector Wrist = DunkStyle == EHCDunkStyle::Windmill ? BoneLocation(TEXT("hand_r"))
			: (BoneLocation(TEXT("hand_l")) + BoneLocation(TEXT("hand_r"))) * 0.5f;
		const FVector Correction = Anchor - Wrist - FVector(0.f, 0.f, 7.f);
		AddActorWorldOffset(Correction.GetClampedToMaxSize(400.f * Dt));
		if (StateTime >= 0.46f)
		{
			DropFromDunk();
		}
		break;
	}

	case EHCPState::DunkLand:
		if (M->IsMovingOnGround() && (!Anim || Anim->GetTime() >= 7.f / 30.f))
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Pass:
		if (StateTime >= 0.15f && !bActionDone)
		{
			bActionDone = true;
			if (HasBall())
			{
				G->ReleasePass(this, ActionTarget, bActionAlley);
			}
		}
		if (StateTime >= 0.36f)
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Shove:
		if (StateTime >= 0.16f && !bActionDone)
		{
			bActionDone = true;
			G->ResolveShove(this, FindShoveOpponent(GetActorForwardVector(), 112.f));
		}
		if (StateTime >= 0.5f)
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Steal:
		if (StateTime >= 0.13f && !bActionDone)
		{
			bActionDone = true;
			G->ResolveSteal(this);
		}
		if (StateTime >= 0.38f)
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Block:
		if (StateTime >= 0.06f && !bActionDone)
		{
			bActionDone = true;
			LaunchCharacter(FVector(M->Velocity.X * 0.3f, M->Velocity.Y * 0.3f, 660.f), true, true);
			G->OnJump(this);
		}
		if (StateTime > 0.2f && !M->IsFalling())
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Stagger:
		if (StateTime >= 0.32f && !M->IsFalling())
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::KnockedDown:
		if (StateTime >= 1.0f && !M->IsFalling())
		{
			SetState(EHCPState::GetUp);
			PlayAnim(EHCAnim::GetUp, false, 1.15f, 0.1f, 0.f, true);
		}
		break;

	case EHCPState::GetUp:
		if (StateTime >= 0.72f)
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Celebrate:
		if (StateTime > 0.9f && !M->IsFalling())
		{
			SetState(EHCPState::Free);
		}
		break;

	case EHCPState::Inbound:
		M->StopMovementImmediately();
		break;
	}
}

void AHCCharacter::DropFromDunk()
{
	GetMesh()->SetRelativeLocationAndRotation(FVector(0, 0, -HC::PlayerHalfHeight), FRotator(0, -90, 0));
	SetState(EHCPState::DunkLand);
	GetCharacterMovement()->SetMovementMode(MOVE_Falling);
	LaunchCharacter(-GetActorForwardVector() * 90.f, true, true);
	PlayAnim(EHCAnim::Land, false, 0.f, 0.14f, 0.f, true);
}

void AHCCharacter::TickMovement(float Dt)
{
	UCharacterMovementComponent* M = GetCharacterMovement();
	AHCGameMode* G = GM();
	const AHCCharacter* Handler = G->Ball ? G->Ball->GetHolder() : nullptr;
	bGuardingBall = State == EHCPState::Free && Handler && Handler->Team != Team && G->IsPlayLive()
		&& !Input.bTurbo && FVector::DistSquared2D(GetActorLocation(), Handler->GetActorLocation()) < FMath::Square(380.f)
		&& FVector::DotProduct(FVector(Input.Move, 0.f).GetSafeNormal2D(),
			(Handler->GetActorLocation() - GetActorLocation()).GetSafeNormal2D()) < 0.65f;
	M->MaxWalkSpeed = bGuardingBall ? MaxSpeed() * 0.58f : MaxSpeed();
	float Scale = 0.f;
	switch (State)
	{
	case EHCPState::Free: Scale = 1.f; break;
	case EHCPState::Pass: Scale = 0.55f; break;
	case EHCPState::Steal: Scale = 0.6f; break;
	case EHCPState::Celebrate: Scale = 0.5f; break;
	default: Scale = 0.f; break;
	}
	if (Scale > 0.f && G->Phase != EHCPhase::Intro && G->Phase != EHCPhase::TipOff && !Input.Move.IsNearlyZero())
	{
		FVector Dir(Input.Move.X, Input.Move.Y, 0.f);
		const float Mag = FMath::Min(1.f, Dir.Size());
		AddMovementInput(Dir.GetSafeNormal(), Mag * Scale);
	}
	// Compare the cut input to current momentum; consecutive velocity samples
	// barely change direction at high frame rates.
	const FVector V = GetVelocity();
	const FVector Intent(Input.Move, 0.f);
	if (State == EHCPState::Free && M->IsMovingOnGround() && SqueakCooldown <= 0.f
		&& V.SizeSquared2D() > FMath::Square(300.f) && Intent.SizeSquared() > 0.25f
		&& FVector::DotProduct(V.GetSafeNormal2D(), Intent.GetSafeNormal2D()) < 0.55f)
	{
		if (G->Audio)
		{
			G->Audio->SfxVariant(TEXT("S_Squeak"), 4, 0.35f, 0.1f);
		}
		SqueakCooldown = 0.45f;
	}
}

void AHCCharacter::TickTurbo(float Dt)
{
	if (bOnFire)
	{
		Turbo = 1.f;
		return;
	}
	const bool bUsing = Input.bTurbo && GetVelocity().Size2D() > 250.f && State == EHCPState::Free;
	if (bUsing)
	{
		Turbo = FMath::Max(0.f, Turbo - Dt * 0.36f);
	}
	else if (!Input.bTurbo)
	{
		Turbo = FMath::Min(1.f, Turbo + Dt * 0.17f);
	}
}

void AHCCharacter::TickFacing(float Dt)
{
	if (State == EHCPState::DunkAir || State == EHCPState::DunkHang || State == EHCPState::KnockedDown || State == EHCPState::GetUp)
	{
		return;
	}
	AHCGameMode* G = GM();
	if (State == EHCPState::Free || State == EHCPState::Celebrate)
	{
		const FVector V = GetVelocity();
		if (bGuardingBall)
		{
			FaceTowards(G->Ball->GetHolder()->GetActorLocation(), Dt);
		}
		else if (V.Size2D() > 70.f)
		{
			DesiredYaw = V.Rotation().Yaw;
		}
		else if (HasBall())
		{
			FaceTowards(G->RimCenter(AttackHoop()), Dt);
		}
		else if (G->Ball)
		{
			FaceTowards(G->Ball->GetActorLocation(), Dt);
		}
	}
	else if (State == EHCPState::Inbound)
	{
		if (AHCCharacter* Mate = G->Teammate(this))
		{
			FaceTowards(Mate->GetActorLocation(), Dt);
		}
	}
	const float Cur = GetActorRotation().Yaw;
	const float Diff = FRotator::NormalizeAxis(DesiredYaw - Cur);
	const float Step = FMath::Clamp(Diff, -900.f * Dt, 900.f * Dt);
	SetActorRotation(FRotator(0.f, Cur + Step, 0.f));
}

void AHCCharacter::TickLocomotionAnim(float Dt)
{
	AHCGameMode* G = GM();
	const float Sp = GetVelocity().Size2D();
	const bool bMoving = Sp > (IsStride(CurAnim) ? 40.f : 75.f);
	const float StrideSpeed = Sp / Def.Build;
	if (HasBall())
	{
		if (G->Phase == EHCPhase::Scored || G->Phase == EHCPhase::Violation)
		{
			PlayAnim(EHCAnim::HoldBall, true, 1.f, 0.15f);
		}
		else if (bMoving)
		{
			PlayAnim(EHCAnim::RunDribble, true, FMath::Clamp(StrideSpeed / 365.f, 0.48f, 2.25f), 0.15f);
		}
		else
		{
			PlayAnim(EHCAnim::DribbleIdle, true, 1.f, 0.15f);
		}
		return;
	}
	if (bMoving)
	{
		const FVector Direction = GetVelocity().GetSafeNormal2D();
		const float Side = FVector::DotProduct(GetActorRightVector(), Direction);
		const float Forward = FVector::DotProduct(GetActorForwardVector(), Direction);
		if (bGuardingBall && Forward < 0.65f)
		{
			const bool bBack = Forward < -0.70f;
			const EHCAnim Step = bBack ? EHCAnim::Backpedal : (Side < 0.f ? EHCAnim::ShuffleLeft : EHCAnim::ShuffleRight);
			PlayAnim(Step, true, FMath::Clamp(StrideSpeed / (bBack ? 195.f : 120.f), 0.45f, 2.35f), 0.12f);
		}
		else if (Input.bTurbo && Sp > (CurAnim == EHCAnim::Sprint ? 570.f : 625.f))
		{
			PlayAnim(EHCAnim::Sprint, true, FMath::Clamp(StrideSpeed / 543.f, 0.70f, 1.65f), 0.15f);
		}
		else
		{
			PlayAnim(EHCAnim::Run, true, FMath::Clamp(StrideSpeed / 397.f, 0.45f, 1.85f), 0.15f);
		}
	}
	else
	{
		const bool bDefending = G->PossessionTeam >= 0 && G->PossessionTeam != Team && G->IsPlayLive();
		PlayAnim(bDefending ? EHCAnim::Defense : EHCAnim::Idle, true, 1.f, 0.2f);
	}
}

void AHCCharacter::TickFX(float Dt)
{
	AHCGameMode* G = GM();
	if (bOnFire)
	{
		FireFXAccum += Dt * 40.f;
		while (FireFXAccum >= 1.f)
		{
			FireFXAccum -= 1.f;
			const FName Bones[] = { TEXT("foot_l"), TEXT("foot_r"), TEXT("hand_l"), TEXT("hand_r") };
			const FVector P = BoneLocation(Bones[FMath::RandRange(0, 3)]) + FMath::VRand() * 6.f;
			FX->Emit(P, FVector(0, 0, FMath::FRandRange(80.f, 160.f)), FMath::FRandRange(0.25f, 0.45f), FMath::FRandRange(16.f, 26.f), 4.f,
				FLinearColor(1.f, 0.75f, 0.3f, 1.f), FLinearColor(0.9f, 0.12f, 0.02f, 0.f), -50.f, 2.f);
		}
	}
	if (RingMID)
	{
		FLinearColor C = TeamColor;
		float Alpha = 0.55f;
		float Inner = 0.80f;
		if (bHuman)
		{
			C = HumanIndex == 0 ? FLinearColor(1.f, 0.85f, 0.1f) : FLinearColor(0.15f, 0.75f, 1.f);
			Alpha = 0.95f;
			Inner = 0.70f;
		}
		if (bOnFire)
		{
			C = FLinearColor(1.f, 0.35f, 0.02f);
			Alpha = 0.8f + 0.2f * FMath::Sin(GetWorld()->GetTimeSeconds() * 12.f);
		}
		RingMID->SetVectorParameterValue(TEXT("Color"), C);
		RingMID->SetScalarParameterValue(TEXT("Alpha"), (G && G->InMenus()) ? Alpha * 0.5f : Alpha);
		RingMID->SetScalarParameterValue(TEXT("Inner"), Inner);
	}
	// ring stays on the floor even while jumping
	const FVector L = GetActorLocation();
	Ring->SetWorldLocation(FVector(L.X, L.Y, 1.5f));
}

void AHCCharacter::Landed(const FHitResult& Hit)
{
	Super::Landed(Hit);
	if (State == EHCPState::DunkLand && Anim)
	{
		Anim->SetRate(1.f);
	}
	if (AHCGameMode* G = GM())
	{
		if (G->Audio && (State == EHCPState::Celebrate || State == EHCPState::Block || State == EHCPState::ShootAir))
		{
			G->Audio->SfxVariant(TEXT("S_Squeak"), 4, 0.25f, 0.1f);
		}
	}
}
