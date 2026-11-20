#include "HCBall.h"
#include "HCCharacter.h"
#include "HCGameMode.h"
#include "HCHoop.h"
#include "HCSpriteFX.h"
#include "HCAudio.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"
#include "Kismet/GameplayStatics.h"

static const FVector GVec(0.f, 0.f, -HC::Gravity);

AHCBall::AHCBall()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	RootComponent = Mesh;
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(true);
	Mesh->SetMobility(EComponentMobility::Movable);
	static ConstructorHelpers::FObjectFinder<UStaticMesh> M(TEXT("/Game/HeatCheck/Meshes/SM_Ball.SM_Ball"));
	if (M.Succeeded())
	{
		Mesh->SetStaticMesh(M.Object);
	}
	FireFX = CreateDefaultSubobject<UHCSpriteFX>(TEXT("FireFX"));
	FireFX->SetupAttachment(Mesh);
}

void AHCBall::BeginPlay()
{
	Super::BeginPlay();
	FireFX->InitPool(220, LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/HeatCheck/Materials/MI_FXFire.MI_FXFire")));
	Pos = GetActorLocation();
}

AHCGameMode* AHCBall::GM() const
{
	if (!CachedGM.IsValid())
	{
		CachedGM = Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this));
	}
	return CachedGM.Get();
}

void AHCBall::GiveTo(AHCCharacter* NewHolder)
{
	if (!NewHolder)
	{
		return;
	}
	State = EHCBallState::Held;
	Holder = NewHolder;
	PassFrom = nullptr;
	PassTo = nullptr;
	bAlley = false;
	Velocity = FVector::ZeroVector;
	LastTouchTeam = NewHolder->Team;
	bFireTrail = NewHolder->bOnFire;
	DribblePhasePrev = 0.f;
	NetDragTime = 0.f;
}

void AHCBall::SetLoose(const FVector& InVelocity, AHCCharacter* Toucher)
{
	State = EHCBallState::Loose;
	Holder = nullptr;
	PassFrom = nullptr;
	PassTo = nullptr;
	Velocity = InVelocity;
	bAnalytic = false;
	if (Toucher)
	{
		LastTouchTeam = Toucher->Team;
	}
}

void AHCBall::SetDead()
{
	State = EHCBallState::Dead;
	Holder = nullptr;
	PassFrom = nullptr;
	PassTo = nullptr;
	bAnalytic = false;
	bFireTrail = false;
}

void AHCBall::LaunchShot(AHCCharacter* InShooter, int32 HoopIndex, int32 Points, bool bMake, bool bFire, float FlightTime, const FVector& Target)
{
	State = EHCBallState::Shot;
	Holder = nullptr;
	Shooter = InShooter;
	LastShooter = InShooter;
	LastTouchTeam = InShooter ? InShooter->Team : -1;
	ShotHoop = HoopIndex;
	ShotPoints = Points;
	bShotMake = bMake;
	bShotFire = bFire;
	bShotScored = false;
	bRimTouched = false;
	bAnalytic = true;
	ShotT = 0.f;
	SinceShot = 0.f;
	ShotDuration = FMath::Max(0.25f, FlightTime);
	ShotStart = Pos;
	const float T = ShotDuration;
	ShotV0 = (Target - ShotStart) / T - 0.5f * GVec * T;
	Velocity = ShotV0;
	bFireTrail = bFire;
}

void AHCBall::LaunchPass(AHCCharacter* From, AHCCharacter* To, bool bInAlley, const FVector& InAlleyPoint)
{
	State = EHCBallState::Pass;
	Holder = nullptr;
	PassFrom = From;
	PassTo = To;
	bAlley = bInAlley;
	AlleyPoint = InAlleyPoint;
	PassStart = Pos;
	PassT = 0.f;
	const FVector Dest = bAlley ? AlleyPoint : To->HandsCenter() + To->GetVelocity() * 0.2f;
	const float Dist = FVector::Dist(Dest, PassStart);
	PassDuration = bAlley ? FMath::Clamp(Dist / 1000.f, 0.55f, 1.05f) : FMath::Clamp(Dist / 1500.f, 0.18f, 0.85f);
	InterceptTried.Reset();
	LastTouchTeam = From ? From->Team : LastTouchTeam;
	bFireTrail = From && From->bOnFire;
}

void AHCBall::DunkThrough(int32 HoopIndex)
{
	const FVector R = GM() ? GM()->RimCenter(HoopIndex) : FVector::ZeroVector;
	State = EHCBallState::Loose;
	Holder = nullptr;
	Pos = R + FVector(0, 0, 6.f);
	Velocity = FVector(0, 0, -520.f);
	bShotScored = true;
	bAnalytic = false;
	NetDragTime = 0.35f;
	ShotHoop = HoopIndex;
}

void AHCBall::HoldForTip(const FVector& Grip)
{
	if (State != EHCBallState::Official)
	{
		SetDead();
		State = EHCBallState::Official;
		Velocity = FVector::ZeroVector;
		LastTouchTeam = -1;
		LastShooter = nullptr;
		Shooter = nullptr;
		bRimTouched = false;
		bAlley = false;
		NetDragTime = 0.f;
	}
	Pos = Grip;
	SetActorLocation(Grip);
}

void AHCBall::Toss(const FVector& From, float UpSpeed)
{
	State = EHCBallState::Loose;
	Holder = nullptr;
	Pos = From;
	Velocity = FVector(0, 0, UpSpeed);
	LastShooter = nullptr;
	bShotScored = true;
	bAnalytic = false;
	bFireTrail = false;
	SetActorLocation(Pos);
}

void AHCBall::Deflect(const FVector& NewVelocity, AHCCharacter* By)
{
	State = EHCBallState::Loose;
	Holder = nullptr;
	Velocity = NewVelocity;
	bAnalytic = false;
	bShotScored = true;     // a blocked shot can no longer count
	LastShooter = nullptr;
	if (By)
	{
		LastTouchTeam = By->Team;
	}
}

FVector AHCBall::PredictPosition(float T) const
{
	if (State == EHCBallState::Shot && bAnalytic)
	{
		const float TT = ShotT + T;
		return ShotStart + ShotV0 * TT + 0.5f * GVec * TT * TT;
	}
	return Pos + Velocity * T + 0.5f * GVec * T * T;
}

FVector AHCBall::PredictRebound() const
{
	if (State == EHCBallState::Shot && GM())
	{
		const FVector R = GM()->RimCenter(ShotHoop);
		const FVector Toward = GM()->Hoops[ShotHoop] ? GM()->Hoops[ShotHoop]->Facing() : FVector::ZeroVector;
		return FVector(R.X + Toward.X * 160.f, R.Y + Toward.Y * 160.f, 0.f);
	}
	// simple ballistic search for the point where the ball comes down to ~1.8 m
	FVector P = Pos;
	FVector V = Velocity;
	for (int32 i = 0; i < 60; ++i)
	{
		const float H = 0.03f;
		V += GVec * H;
		P += V * H;
		if (V.Z < 0.f && P.Z < 180.f)
		{
			break;
		}
	}
	return FVector(P.X, P.Y, 0.f);
}

void AHCBall::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const float Dt = FMath::Min(DeltaSeconds, 1.f / 20.f);
	SoundCooldown -= Dt;
	SinceShot += Dt;
	switch (State)
	{
	case EHCBallState::Official:
		return;
	case EHCBallState::Held:
		UpdateHeld(Dt);
		break;
	case EHCBallState::Shot:
		UpdateShot(Dt);
		break;
	case EHCBallState::Pass:
		UpdatePass(Dt);
		break;
	case EHCBallState::Loose:
	case EHCBallState::Dead:
		StepPhysics(Dt, true);
		break;
	}
	SetActorLocation(Pos);
	SpinVisual(Dt);

	if (bFireTrail && State != EHCBallState::Dead)
	{
		FireEmitAccum += Dt * 90.f;
		while (FireEmitAccum >= 1.f)
		{
			FireEmitAccum -= 1.f;
			const FVector Back = -Velocity.GetSafeNormal() * FMath::FRandRange(0.f, 10.f);
			FireFX->Emit(Pos + Back + FMath::VRand() * 6.f, FVector(0, 0, FMath::FRandRange(60.f, 160.f)) - Velocity * 0.08f,
				FMath::FRandRange(0.25f, 0.5f), FMath::FRandRange(24.f, 34.f), 6.f,
				FLinearColor(1.f, 0.78f, 0.3f, 1.f), FLinearColor(0.9f, 0.15f, 0.02f, 0.f), -60.f, 2.f);
		}
	}
}

void AHCBall::UpdateHeld(float Dt)
{
	if (!Holder)
	{
		State = EHCBallState::Loose;
		return;
	}
	bFireTrail = Holder->bOnFire;
	const EHCBallHold H = Holder->GetBallHold();
	FVector Target;
	if (H == EHCBallHold::Dribble)
	{
		const FVector Hand = Holder->BoneLocation(TEXT("grip_r"));
		const float T = Holder->GetDribblePhase();
		const float FloorZ = HC::BallRadius;
		const float HandZ = FMath::Max(Hand.Z, FloorZ + 30.f);
		float Z;
		if (T < 0.45f)
		{
			const float K = T / 0.45f;
			Z = HandZ + (FloorZ - HandZ) * K * K;
		}
		else
		{
			const float K = (T - 0.45f) / 0.55f;
			Z = FloorZ + (HandZ - FloorZ) * (1.f - (1.f - K) * (1.f - K));
		}
		if (DribblePhasePrev < 0.45f && T >= 0.45f && GM())
		{
			GM()->OnBallBounce(300.f);
		}
		DribblePhasePrev = T;
		// lead the ball slightly in the direction of travel so it stays out of the legs
		const FVector Lead = Holder->GetVelocity() * (0.05f * (1.f - FMath::Square(2.f * T - 1.f)));
		Target = FVector(Hand.X + Lead.X, Hand.Y + Lead.Y, Z);
	}
	else if (H == EHCBallHold::TwoHands)
	{
		Target = Holder->HandsCenter();
	}
	else
	{
		Target = Holder->BoneLocation(TEXT("grip_r"));
	}
	Velocity = (Target - Pos) / FMath::Max(Dt, 1e-3f);
	Pos = Target;
}

void AHCBall::UpdateShot(float Dt)
{
	ShotT += Dt;
	if (bAnalytic)
	{
		const FVector Prev = Pos;
		Pos = ShotStart + ShotV0 * ShotT + 0.5f * GVec * ShotT * ShotT;
		Velocity = ShotV0 + GVec * ShotT;
		if (bShotMake)
		{
			CheckThroughHoop(ShotHoop, Prev, Pos);
		}
		else if (GM())
		{
			const FVector R = GM()->RimCenter(ShotHoop);
			if (FVector::Dist(Pos, R) < 48.f || ShotT >= ShotDuration * 0.97f)
			{
				bAnalytic = false;
			}
		}
		if (ShotT > ShotDuration + 0.6f)
		{
			bAnalytic = false;
		}
	}
	else
	{
		StepPhysics(Dt, true);
	}
}

void AHCBall::UpdatePass(float Dt)
{
	if (!PassTo)
	{
		SetLoose(Velocity * 0.4f);
		return;
	}
	PassT += Dt;
	const float U = FMath::Clamp(PassT / PassDuration, 0.f, 1.f);
	FVector Dest = bAlley ? AlleyPoint : PassTo->HandsCenter();
	if (bAlley && PassTo->IsDunking() && U > 0.55f)
	{
		Dest = FMath::Lerp(AlleyPoint, PassTo->HandsCenter(), FMath::Clamp((U - 0.55f) / 0.35f, 0.f, 1.f));
	}
	const float Dist = FVector::Dist(PassStart, Dest);
	const float Arc = bAlley ? 110.f : 18.f + 0.03f * Dist;
	const FVector P = FMath::Lerp(PassStart, Dest, U) + FVector(0, 0, Arc * 4.f * U * (1.f - U));
	Velocity = (P - Pos) / FMath::Max(Dt, 1e-3f);
	Pos = P;

	if (GM() && PassFrom)
	{
		TArray<AHCCharacter*> Opp;
		GM()->GetOpponents(PassFrom, Opp);
		for (AHCCharacter* O : Opp)
		{
			if (!O || !O->CanReceiveBall() || InterceptTried.Contains(O))
			{
				continue;
			}
			const float D = FVector::Dist(O->HandsCenter(), Pos);
			if (D < 58.f)
			{
				InterceptTried.Add(O);
				float Chance = 0.14f + O->Def.Steal * 0.025f;
				if (O->State == EHCPState::Steal || O->State == EHCPState::Block)
				{
					Chance += 0.25f;
				}
				if (bAlley)
				{
					Chance *= 0.5f;
				}
				if (GM()->Phase == EHCPhase::Inbound)
				{
					Chance *= 0.25f;
				}
				if (FMath::FRand() < Chance)
				{
					AHCCharacter* From = PassFrom;
					GiveTo(O);
					GM()->OnPassIntercepted(O, From);
					return;
				}
			}
		}
	}

	if (U >= 1.f)
	{
		AHCCharacter* From = PassFrom;
		AHCCharacter* To = PassTo;
		const bool bReachable = !bAlley || (To->State == EHCPState::DunkAir
			&& FVector::DistSquared(Pos, To->HandsCenter()) < FMath::Square(50.f));
		if (To->CanReceiveBall() && bReachable)
		{
			GiveTo(To);
			if (GM())
			{
				GM()->OnBallCaught(To, From);
			}
		}
		else
		{
			SetLoose(Velocity * 0.3f);
		}
	}
}

void AHCBall::StepPhysics(float Dt, bool bCollide)
{
	const int32 N = FMath::Clamp(FMath::CeilToInt(Velocity.Size() * Dt / 3.f), 1, 16);
	const float H = Dt / N;
	const float R = HC::BallRadius;
	for (int32 i = 0; i < N; ++i)
	{
		const FVector Prev = Pos;
		Velocity += GVec * H;
		if (NetDragTime > 0.f && GM())
		{
			NetDragTime -= H;
			const FVector RC = GM()->RimCenter(ShotHoop);
			Velocity.X = FMath::Lerp(Velocity.X, (RC.X - Pos.X) * 4.f, FMath::Min(1.f, 10.f * H));
			Velocity.Y = FMath::Lerp(Velocity.Y, (RC.Y - Pos.Y) * 4.f, FMath::Min(1.f, 10.f * H));
			Velocity.Z = FMath::Max(Velocity.Z, -240.f);
		}
		Pos += Velocity * H;

		// floor
		if (Pos.Z < R)
		{
			Pos.Z = R;
			if (Velocity.Z < 0.f)
			{
				const float Sp = -Velocity.Z;
				if (Sp > 60.f)
				{
					Velocity.Z = Sp * 0.74f;
					if (GM() && SoundCooldown <= 0.f)
					{
						GM()->OnBallBounce(Sp);
						SoundCooldown = 0.05f;
					}
				}
				else
				{
					Velocity.Z = 0.f;
				}
				Velocity.X *= 0.93f;
				Velocity.Y *= 0.93f;
				if (State == EHCBallState::Shot)
				{
					State = EHCBallState::Loose;
				}
			}
		}
		if (Pos.Z <= R + 0.5f && FMath::Abs(Velocity.Z) < 1.f)
		{
			Velocity.X *= FMath::Max(0.f, 1.f - 0.9f * H);
			Velocity.Y *= FMath::Max(0.f, 1.f - 0.9f * H);
		}
		// soft walls just outside the court (the crowd tosses it back)
		const float WX = HC::CourtHalfLength + 170.f;
		const float WY = HC::CourtHalfWidth + 150.f;
		if (FMath::Abs(Pos.X) > WX)
		{
			Pos.X = FMath::Sign(Pos.X) * WX;
			Velocity.X *= -0.45f;
		}
		if (FMath::Abs(Pos.Y) > WY)
		{
			Pos.Y = FMath::Sign(Pos.Y) * WY;
			Velocity.Y *= -0.45f;
		}
		if (bCollide)
		{
			for (int32 Hi = 0; Hi < 2; ++Hi)
			{
				CollideRim(Hi, Pos, Velocity);
				CollideBackboard(Hi, Pos, Velocity);
			}
		}
		if (!bShotScored && LastShooter && SinceShot < 5.f)
		{
			CheckThroughHoop(ShotHoop, Prev, Pos);
		}
	}
}

void AHCBall::CollideRim(int32 Hi, FVector& P, FVector& V)
{
	if (!GM())
	{
		return;
	}
	const FVector C = GM()->RimCenter(Hi);
	const FVector D = P - C;
	if (FMath::Abs(D.Z) > 30.f || D.Size2D() > 60.f)
	{
		return;
	}
	const FVector2D Dxy(D.X, D.Y);
	const float L = Dxy.Size();
	const float Rr = HC::RimRadius + HC::RimTube;
	const FVector Q = L < 1e-3f ? C + FVector(Rr, 0, 0) : C + FVector(Dxy.X / L * Rr, Dxy.Y / L * Rr, 0.f);
	FVector Nrm = P - Q;
	const float Dist = Nrm.Size();
	const float MinD = HC::BallRadius + HC::RimTube;
	if (Dist < MinD && Dist > 1e-4f)
	{
		Nrm /= Dist;
		P = Q + Nrm * MinD;
		const float Vn = FVector::DotProduct(V, Nrm);
		if (Vn < 0.f)
		{
			V -= (1.f + 0.55f) * Vn * Nrm;
			V *= 0.9f;
			// a little randomness keeps rebounds lively
			V += FVector(FMath::FRandRange(-25.f, 25.f), FMath::FRandRange(-25.f, 25.f), 0.f);
			if (!bRimTouched || SoundCooldown <= 0.f)
			{
				bRimTouched = true;
				GM()->OnBallRim(Hi, -Vn);
				SoundCooldown = 0.06f;
			}
			if (State == EHCBallState::Shot)
			{
				State = EHCBallState::Loose;
			}
		}
	}
}

void AHCBall::CollideBackboard(int32 Hi, FVector& P, FVector& V)
{
	const float Sign = Hi == 1 ? 1.f : -1.f;
	const float FaceX = Sign * HC::BackboardX;
	const float MinX = Sign > 0.f ? FaceX : FaceX - 3.f;
	const float MaxX = Sign > 0.f ? FaceX + 3.f : FaceX;
	const FVector Cl(FMath::Clamp(P.X, MinX, MaxX), FMath::Clamp(P.Y, -HC::BackboardHalfWidth, HC::BackboardHalfWidth),
		FMath::Clamp(P.Z, HC::BackboardBottom, HC::BackboardTop));
	const FVector D = P - Cl;
	const float Dist = D.Size();
	if (Dist < HC::BallRadius)
	{
		const FVector Nrm = Dist > 1e-4f ? D / Dist : FVector(-Sign, 0.f, 0.f);
		P = Cl + Nrm * HC::BallRadius;
		const float Vn = FVector::DotProduct(V, Nrm);
		if (Vn < 0.f)
		{
			V -= (1.f + 0.6f) * Vn * Nrm;
			if (GM() && SoundCooldown <= 0.f)
			{
				GM()->OnBallBoard(Hi, -Vn);
				SoundCooldown = 0.06f;
			}
			if (State == EHCBallState::Shot)
			{
				State = EHCBallState::Loose;
			}
		}
	}
}

void AHCBall::CheckThroughHoop(int32 Hi, const FVector& PrevP, const FVector& P)
{
	if (!GM() || bShotScored)
	{
		return;
	}
	const FVector R = GM()->RimCenter(Hi);
	if (PrevP.Z >= R.Z && P.Z < R.Z)
	{
		const float A = (PrevP.Z - R.Z) / FMath::Max(1e-4f, PrevP.Z - P.Z);
		const FVector X = PrevP + (P - PrevP) * A;
		if (FVector::Dist2D(X, R) < HC::RimRadius - 1.5f)
		{
			bShotScored = true;
			bAnalytic = false;
			NetDragTime = 0.45f;
			Velocity.X *= 0.3f;
			Velocity.Y *= 0.3f;
			Velocity.Z = FMath::Min(Velocity.Z, -150.f);
			if (State == EHCBallState::Shot)
			{
				State = EHCBallState::Loose;
			}
			GM()->OnBallScored(Hi, LastShooter, ShotPoints, false);
		}
	}
}

void AHCBall::SpinVisual(float Dt)
{
	FVector Axis = FVector::ZeroVector;
	float W = 0.f;
	if (State == EHCBallState::Shot)
	{
		Axis = FVector::CrossProduct(FVector::UpVector, Velocity.GetSafeNormal2D());
		W = -14.f;
	}
	else
	{
		Axis = FVector::CrossProduct(FVector::UpVector, Velocity.GetSafeNormal2D());
		W = Velocity.Size2D() / HC::BallRadius * 0.6f;
		if (State == EHCBallState::Held)
		{
			W = FMath::Min(W, 6.f) + 2.f;
			if (Axis.IsNearlyZero())
			{
				Axis = FVector::RightVector;
			}
		}
	}
	if (!Axis.IsNearlyZero() && W != 0.f)
	{
		SpinQuat = FQuat(Axis.GetSafeNormal(), W * Dt) * SpinQuat;
		SpinQuat.Normalize();
	}
	Mesh->SetWorldRotation(SpinQuat);
}
