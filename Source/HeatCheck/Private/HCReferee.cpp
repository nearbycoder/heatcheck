#include "HCReferee.h"
#include "HCAnimInstance.h"
#include "HCTypes.h"
#include "Animation/AnimSequence.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "UObject/ConstructorHelpers.h"

AHCReferee::AHCReferee()
{
	Body = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Official"));
	RootComponent = Body;
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> Mesh(TEXT("/Game/HeatCheck/Characters/SK_Referee"));
	static ConstructorHelpers::FObjectFinder<UAnimSequence> ThrowClip(TEXT("/Game/HeatCheck/Anims/A_RefToss"));
	static ConstructorHelpers::FObjectFinder<UAnimSequence> RunClip(TEXT("/Game/HeatCheck/Anims/A_Run"));
	static ConstructorHelpers::FObjectFinder<UAnimSequence> IdleClip(TEXT("/Game/HeatCheck/Anims/A_Idle"));
	Body->SetSkeletalMesh(Mesh.Object);
	Body->SetAnimInstanceClass(UHCAnimInstance::StaticClass());
	Toss = ThrowClip.Object;
	Run = RunClip.Object;
	Idle = IdleClip.Object;
}

void AHCReferee::LineUp()
{
	SetActorLocationAndRotation(FVector(0, -36, 0), FRotator::ZeroRotator);
	SetActorScale3D(FVector(0.95f));
	SinceRelease = -1.f;
	bOnSideline = false;
	bJogging = false;
	Anim = CastChecked<UHCAnimInstance>(Body->GetAnimInstance());
	Anim->Play(Toss, false, 0.f, 0.f, 0.f, true);
	// The game clock samples the held ball and both hands from the same pose.
	Body->SetComponentTickEnabled(false);
}

FVector AHCReferee::PoseToss(float Time)
{
	Anim->SetTime(Time);
	Body->TickAnimation(0.f, false);
	Body->RefreshBoneTransforms();
	static const FName Left(TEXT("grip_l")), Right(TEXT("grip_r"));
	return (Body->GetSocketLocation(Left) + Body->GetSocketLocation(Right)) * 0.5f;
}

void AHCReferee::FollowThrough()
{
	SinceRelease = 0.f;
	Anim->SetRate(1.f);
	Body->SetComponentTickEnabled(true);
}

void AHCReferee::TrackPlay(float Dt, const FVector& Ball)
{
	if (SinceRelease < 0.f)
	{
		return;
	}
	SinceRelease += Dt;
	if (SinceRelease < 0.48f)
	{
		return;
	}
	const FVector Loc = GetActorLocation();
	const float Sideline = -HC::CourtHalfWidth - 48.f;
	const FVector Target(bOnSideline ? FMath::Clamp(Ball.X * 0.62f, -740.f, 740.f) : 0.f, Sideline, 0);
	const FVector To = Target - Loc;
	const float Distance = To.Size2D();
	// Use a wider threshold to start running than to stop, so a dribble or a
	// change of possession does not restart the footwork on every frame.
	bJogging = Distance > (bJogging ? 16.f : 150.f);
	bOnSideline |= FMath::Abs(Loc.Y - Sideline) < 17.f;
	const FVector Facing = bJogging ? To : Ball - Loc;
	const float Yaw = FMath::FixedTurn(GetActorRotation().Yaw, Facing.Rotation().Yaw - 90.f, 380.f * Dt);
	SetActorRotation(FRotator(0, Yaw, 0));
	if (bJogging)
	{
		const float Speed = FMath::Clamp(Distance * 4.f, 115.f, 405.f);
		SetActorLocation(Loc + To.GetSafeNormal2D() * FMath::Min(Distance, Speed * Dt));
		Anim->Play(Run, true, Speed / 350.f);
	}
	else
	{
		Anim->Play(Idle, true);
	}
}
