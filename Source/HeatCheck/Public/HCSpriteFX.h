#pragma once

#include "CoreMinimal.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "HCSpriteFX.generated.h"

/**
 * Tiny CPU particle system rendered as camera-facing quads in one instanced mesh.
 * Per-instance custom data (r,g,b,alpha) drives an additive sprite material.
 * Used for flames (ball on fire, burning net, on-fire players), sparks and glows.
 */
UCLASS(ClassGroup = (HeatCheck), meta = (BlueprintSpawnableComponent))
class HEATCHECK_API UHCSpriteFX : public UInstancedStaticMeshComponent
{
	GENERATED_BODY()
public:
	UHCSpriteFX();

	void InitPool(int32 InMaxParticles, UMaterialInterface* Material);

	void Emit(const FVector& Pos, const FVector& Vel, float Life, float Size0, float Size1,
		const FLinearColor& Color0, const FLinearColor& Color1, float Gravity = 0.f, float Drag = 0.f);

	/** Burst of flame-like particles at Pos (radius spread). */
	void EmitFire(const FVector& Pos, int32 Count, float Radius, float Upward, float Size, float Intensity = 1.f);
	void EmitSparks(const FVector& Pos, int32 Count, float Speed, const FLinearColor& Color);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	int32 NumAlive() const { return Alive; }

private:
	struct FParticle
	{
		FVector Pos;
		FVector Vel;
		float Age = 0.f;
		float Life = 0.f;
		float Size0 = 10.f;
		float Size1 = 10.f;
		FLinearColor C0;
		FLinearColor C1;
		float Gravity = 0.f;
		float Drag = 0.f;
		float Spin = 0.f;
	};
	TArray<FParticle> Particles;
	int32 MaxParticles = 0;
	int32 Next = 0;
	int32 Alive = 0;
};
