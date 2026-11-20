#include "HCHoop.h"
#include "HCTypes.h"
#include "HCSpriteFX.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"

static UStaticMeshComponent* MakeHoopPart(AActor* Owner, USceneComponent* Parent, FName Name, const TCHAR* Path)
{
	UStaticMeshComponent* C = Owner->CreateDefaultSubobject<UStaticMeshComponent>(Name);
	C->SetupAttachment(Parent);
	C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	C->SetGenerateOverlapEvents(false);
	ConstructorHelpers::FObjectFinder<UStaticMesh> F(Path);
	if (F.Succeeded())
	{
		C->SetStaticMesh(F.Object);
	}
	return C;
}

AHCHoop::AHCHoop()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Stanchion = MakeHoopPart(this, Root, TEXT("Stanchion"), TEXT("/Game/HeatCheck/Meshes/SM_HoopStanchion.SM_HoopStanchion"));
	Glass = MakeHoopPart(this, Root, TEXT("Glass"), TEXT("/Game/HeatCheck/Meshes/SM_Backboard.SM_Backboard"));
	Glass->SetCastShadow(false);
	Frame = MakeHoopPart(this, Root, TEXT("Frame"), TEXT("/Game/HeatCheck/Meshes/SM_BackboardFrame.SM_BackboardFrame"));
	Rim = MakeHoopPart(this, Root, TEXT("Rim"), TEXT("/Game/HeatCheck/Meshes/SM_Rim.SM_Rim"));
	Rim->SetRelativeLocation(FVector(-38.f, 0.f, HC::RimZ));
	Net = MakeHoopPart(this, Rim, TEXT("Net"), TEXT("/Game/HeatCheck/Meshes/SM_Net.SM_Net"));
	Net->SetRelativeLocation(FVector(38.f, 0.f, 0.f));
	FX = CreateDefaultSubobject<UHCSpriteFX>(TEXT("FX"));
	FX->SetupAttachment(Root);
}

void AHCHoop::BeginPlay()
{
	Super::BeginPlay();
	FX->InitPool(260, LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/HeatCheck/Materials/MI_FXFire.MI_FXFire")));
}

void AHCHoop::SetIndex(int32 InIndex)
{
	Index = InIndex;
	const float X = Index == 0 ? -HC::RimX : HC::RimX;
	SetActorLocationAndRotation(FVector(X, 0.f, 0.f), FRotator(0.f, Index == 0 ? 0.f : 180.f, 0.f));
}

FVector AHCHoop::RimCenter() const
{
	return FVector(Index == 0 ? -HC::RimX : HC::RimX, 0.f, HC::RimZ);
}

FVector AHCHoop::FloorUnderRim() const
{
	return FVector(Index == 0 ? -HC::RimX : HC::RimX, 0.f, 0.f);
}

FVector AHCHoop::Facing() const
{
	return FVector(Index == 0 ? 1.f : -1.f, 0.f, 0.f);
}

void AHCHoop::Shake(float Amount)
{
	ShakeAmt = Amount;
	ShakeT = 0.f;
}

void AHCHoop::Swish(float Amount)
{
	SwishAmt = Amount;
	SwishT = 0.f;
}

void AHCHoop::SetNetFire(float Seconds)
{
	FireTime = FMath::Max(FireTime, Seconds);
}

void AHCHoop::FlashGlass()
{
	FX->EmitSparks(RimCenter() + FVector(Index == 0 ? -30.f : 30.f, 0.f, 40.f), 40, 500.f, FLinearColor(0.6f, 0.8f, 1.f, 1.f));
}

void AHCHoop::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ShakeT += DeltaSeconds;
	SwishT += DeltaSeconds;
	const float Pitch = -ShakeAmt * FMath::Sin(ShakeT * 34.f) * FMath::Exp(-ShakeT * 4.f);
	Rim->SetRelativeRotation(FRotator(Pitch, 0.f, 0.f));
	const float Sw = SwishAmt * FMath::Sin(SwishT * 20.f) * FMath::Exp(-SwishT * 4.5f);
	Net->SetRelativeScale3D(FVector(1.f - 0.22f * Sw, 1.f - 0.22f * Sw, 1.f + 0.5f * Sw));
	if (FireTime > 0.f)
	{
		FireTime -= DeltaSeconds;
		FireAccum += DeltaSeconds * 110.f;
		const FVector C = RimCenter();
		while (FireAccum >= 1.f)
		{
			FireAccum -= 1.f;
			const float A = FMath::FRandRange(0.f, 2.f * PI);
			const float Z = FMath::FRandRange(-40.f, 2.f);
			const float Rad = FMath::Lerp(14.f, 24.f, (Z + 40.f) / 42.f);
			FX->Emit(C + FVector(FMath::Cos(A) * Rad, FMath::Sin(A) * Rad, Z), FVector(0, 0, FMath::FRandRange(90.f, 220.f)),
				FMath::FRandRange(0.3f, 0.6f), FMath::FRandRange(22.f, 36.f), 6.f,
				FLinearColor(1.f, 0.8f, 0.35f, 1.f), FLinearColor(1.f, 0.15f, 0.02f, 0.f), -80.f, 1.5f);
		}
	}
}
