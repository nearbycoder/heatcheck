#include "HCSpriteFX.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "Camera/PlayerCameraManager.h"
#include "GameFramework/PlayerController.h"
#include "UObject/ConstructorHelpers.h"

UHCSpriteFX::UHCSpriteFX()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = false;
	PrimaryComponentTick.TickGroup = TG_PostUpdateWork;
	SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SetCastShadow(false);
	bAffectDistanceFieldLighting = false;
	bAffectDynamicIndirectLighting = false;
	bAffectIndirectLightingWhileHidden = false;
	bVisibleInReflectionCaptures = false;
	bVisibleInRealTimeSkyCaptures = false;
	bVisibleInRayTracing = false;
	bRenderInDepthPass = false;
	SetGenerateOverlapEvents(false);
	SetCanEverAffectNavigation(false);
	bReceivesDecals = false;
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Plane(TEXT("/Engine/BasicShapes/Plane.Plane"));
	if (Plane.Succeeded())
	{
		SetStaticMesh(Plane.Object);
	}
	NumCustomDataFloats = 4;
}

void UHCSpriteFX::InitPool(int32 InMaxParticles, UMaterialInterface* Material)
{
	MaxParticles = InMaxParticles;
	Particles.Reset();
	Particles.SetNum(MaxParticles);
	Alive = Next = 0;
	SetComponentTickEnabled(false);
	SetNumCustomDataFloats(4);
	if (Material)
	{
		SetMaterial(0, Material);
	}
	ClearInstances();
	TArray<FTransform> Xforms;
	Xforms.SetNum(MaxParticles);
	for (int32 i = 0; i < MaxParticles; ++i)
	{
		Xforms[i] = FTransform(FQuat::Identity, FVector(0, 0, -100000), FVector(0.001f));
	}
	AddInstances(Xforms, false, true);
	// world space instances: keep the component at the origin
	SetUsingAbsoluteLocation(true);
	SetUsingAbsoluteRotation(true);
	SetUsingAbsoluteScale(true);
	SetWorldLocationAndRotation(FVector::ZeroVector, FRotator::ZeroRotator);
	SetWorldScale3D(FVector::OneVector);
	// instances move every frame; keep bounds generous so culling never hides them
	SetBoundsScale(1.f);
}

void UHCSpriteFX::Emit(const FVector& Pos, const FVector& Vel, float Life, float Size0, float Size1,
	const FLinearColor& Color0, const FLinearColor& Color1, float Gravity, float Drag)
{
	if (MaxParticles <= 0)
	{
		return;
	}
	SetComponentTickEnabled(true);
	FParticle& P = Particles[Next];
	P.Pos = Pos;
	P.Vel = Vel;
	P.Age = 0.f;
	P.Life = FMath::Max(0.05f, Life);
	P.Size0 = Size0;
	P.Size1 = Size1;
	P.C0 = Color0;
	P.C1 = Color1;
	P.Gravity = Gravity;
	P.Drag = Drag;
	P.Spin = FMath::FRandRange(-2.f, 2.f);
	Next = (Next + 1) % MaxParticles;
}

void UHCSpriteFX::EmitFire(const FVector& Pos, int32 Count, float Radius, float Upward, float Size, float Intensity)
{
	for (int32 i = 0; i < Count; ++i)
	{
		const FVector Off = FMath::VRand() * FMath::FRandRange(0.f, Radius);
		const FVector V(FMath::FRandRange(-30.f, 30.f), FMath::FRandRange(-30.f, 30.f), Upward * FMath::FRandRange(0.6f, 1.3f));
		const float Life = FMath::FRandRange(0.35f, 0.7f);
		const FLinearColor C0(1.0f * Intensity, 0.75f * Intensity, 0.25f * Intensity, 1.f);
		const FLinearColor C1(0.9f * Intensity, 0.18f * Intensity, 0.02f * Intensity, 0.f);
		Emit(Pos + Off, V, Life, Size * FMath::FRandRange(0.8f, 1.2f), Size * 0.35f, C0, C1, -40.f, 1.5f);
	}
}

void UHCSpriteFX::EmitSparks(const FVector& Pos, int32 Count, float Speed, const FLinearColor& Color)
{
	for (int32 i = 0; i < Count; ++i)
	{
		const FVector V = FMath::VRand() * Speed * FMath::FRandRange(0.4f, 1.f) + FVector(0, 0, Speed * 0.4f);
		Emit(Pos, V, FMath::FRandRange(0.4f, 0.9f), 9.f, 2.f, Color, FLinearColor(Color.R, Color.G * 0.4f, 0.f, 0.f), 900.f, 1.f);
	}
}

void UHCSpriteFX::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (MaxParticles <= 0 || GetInstanceCount() != MaxParticles)
	{
		return;
	}
	FVector CamLoc = FVector(0, 1600, 800);
	if (const APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr)
	{
		if (PC->PlayerCameraManager)
		{
			CamLoc = PC->PlayerCameraManager->GetCameraLocation();
		}
	}
	Alive = 0;
	for (int32 i = 0; i < MaxParticles; ++i)
	{
		FParticle& P = Particles[i];
		if (P.Life <= 0.f)
		{
			continue;
		}
		FTransform Xform;
		P.Age += DeltaTime;
		P.Vel.Z -= P.Gravity * DeltaTime;
		P.Vel *= FMath::Max(0.f, 1.f - P.Drag * DeltaTime);
		P.Pos += P.Vel * DeltaTime;
		const float T = FMath::Clamp(P.Age / P.Life, 0.f, 1.f);
		const FLinearColor C = FMath::Lerp(P.C0, P.C1, T);
		const float Alpha = C.A * FMath::Clamp((1.f - T) * 3.f, 0.f, 1.f);
		const float Size = FMath::Lerp(P.Size0, P.Size1, T);
		if (P.Age >= P.Life)
		{
			P.Life = 0.f;
		}
		else
		{
			++Alive;
		}
		if (Size > 0.f && Alpha > 0.001f)
		{
			// plane mesh faces +Z; rotate so it faces the camera, spin around the view axis
			const FVector ToCam = (CamLoc - P.Pos).GetSafeNormal();
			FQuat Q = FRotationMatrix::MakeFromZ(ToCam).ToQuat();
			Q = Q * FQuat(FVector::UpVector, P.Spin * P.Age);
			Xform = FTransform(Q, P.Pos, FVector(Size / 100.f));
		}
		else
		{
			Xform = FTransform(FQuat::Identity, FVector(0, 0, -100000), FVector(0.001f));
		}
		const float Color[] = { C.R, C.G, C.B, Alpha };
		SetCustomData(i, MakeArrayView(Color));
		UpdateInstanceTransform(i, Xform, false, false, true);
	}
	if (Alive == 0)
	{
		SetComponentTickEnabled(false);
	}
}
