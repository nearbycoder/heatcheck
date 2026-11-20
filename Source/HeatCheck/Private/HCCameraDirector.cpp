#include "HCCameraDirector.h"
#include "HCGameMode.h"
#include "HCBall.h"
#include "HCCharacter.h"
#include "Camera/CameraComponent.h"
#include "Kismet/GameplayStatics.h"

AHCCameraDirector::AHCCameraDirector()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	PrimaryActorTick.bTickEvenWhenPaused = false;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	RootComponent = Camera;
	Camera->SetFieldOfView(56.f);
	Camera->bConstrainAspectRatio = false;
	FPostProcessSettings& PP = Camera->PostProcessSettings;
	PP.bOverride_AutoExposureMethod = true;
	PP.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	PP.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	PP.AutoExposureApplyPhysicalCameraExposure = false;
	PP.bOverride_AutoExposureBias = true;
	PP.AutoExposureBias = 0.0f;
	PP.bOverride_BloomIntensity = true;
	PP.BloomIntensity = 0.85f;
	PP.bOverride_VignetteIntensity = true;
	PP.VignetteIntensity = 0.35f;
	PP.bOverride_ColorSaturation = true;
	PP.ColorSaturation = FVector4(1.12f, 1.12f, 1.12f, 1.f);
	PP.bOverride_ColorContrast = true;
	PP.ColorContrast = FVector4(1.06f, 1.06f, 1.06f, 1.f);
	PP.bOverride_MotionBlurAmount = true;
	PP.MotionBlurAmount = 0.f;
}

void AHCCameraDirector::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const float Dt = FMath::Min(DeltaSeconds, 0.05f);
	Time += Dt;
	AHCGameMode* G = Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this));
	if (!G || !G->Ball)
	{
		return;
	}
	FVector Target = G->Ball->GetActorLocation();
	// lead toward the basket being attacked
	if (G->PossessionTeam >= 0 && G->Phase == EHCPhase::Live)
	{
		const float Dir = G->AttackHoop(G->PossessionTeam) == 1 ? 1.f : -1.f;
		Target.X += Dir * 260.f;
	}
	if (G->Phase == EHCPhase::Intro || G->Phase == EHCPhase::TipOff)
	{
		Target = FVector(0, 0, 150);
	}
	Target.X = FMath::Clamp(Target.X, -860.f, 860.f);

	const bool bJumpBall = G->Phase == EHCPhase::Intro || G->Phase == EHCPhase::TipOff;
	float DesiredZoom = bJumpBall ? 0.86f : 1.f;
	for (AHCCharacter* C : G->Players)
	{
		if (C && C->IsDunking())
		{
			DesiredZoom = 0.86f;
			Target.X = FMath::Clamp(C->GetActorLocation().X, -1000.f, 1000.f);
		}
	}
	if (G->InMenus())
	{
		DesiredZoom = 1.05f;
	}
	if (bSnap)
	{
		Focus = Target;
		Zoom = DesiredZoom;
		bSnap = false;
	}
	Focus.X = FMath::FInterpTo(Focus.X, Target.X, Dt, 2.6f);
	Focus.Y = FMath::FInterpTo(Focus.Y, FMath::Clamp(Target.Y, -400.f, 400.f), Dt, 1.5f);
	Zoom = FMath::FInterpTo(Zoom, DesiredZoom, Dt, 2.5f);

	FVector CamLoc(Focus.X * 0.9f, 1640.f * Zoom + Focus.Y * 0.15f, 870.f * Zoom);
	const FVector LookAt(Focus.X, Focus.Y * 0.35f - 40.f, 90.f + (1.f - Zoom) * 280.f);
	if (G->InMenus())
	{
		// slow drift for the attract mode behind the menus
		CamLoc.X += FMath::Sin(Time * 0.15f) * 250.f;
	}
	ShakeAmt = FMath::Max(0.f, ShakeAmt - Dt * 1.8f);
	if (ShakeAmt > 0.f)
	{
		const float A = ShakeAmt * ShakeAmt * 14.f;
		CamLoc += FVector(FMath::PerlinNoise1D(Time * 23.f) * A, FMath::PerlinNoise1D(Time * 19.f + 7.f) * A, FMath::PerlinNoise1D(Time * 29.f + 3.f) * A);
	}
	SetActorLocation(CamLoc);
	SetActorRotation((LookAt - CamLoc).Rotation());
	Camera->SetFieldOfView(56.f * FMath::Lerp(1.f, Zoom, 0.6f));
}
