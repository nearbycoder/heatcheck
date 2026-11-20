#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "HCAnimInstance.generated.h"

class UAnimSequence;

/** Worker-thread side of the animation: samples the current + previous sequence and crossfades them. */
USTRUCT()
struct FHCAnimProxy : public FAnimInstanceProxy
{
	GENERATED_BODY()

	FHCAnimProxy() {}
	FHCAnimProxy(UAnimInstance* InInstance) : FAnimInstanceProxy(InInstance) {}

	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate(FPoseContext& Output) override;

	TObjectPtr<UAnimSequence> CurSeq = nullptr;
	TObjectPtr<UAnimSequence> PrevSeq = nullptr;
	float CurTime = 0.f;
	float PrevTime = 0.f;
	bool bCurLoop = true;
	bool bPrevLoop = true;
	float Alpha = 1.f;
	float HeadScale = 1.f;
};

/**
 * Native animation instance (no Anim Blueprint needed). Gameplay code calls Play() to switch clips;
 * clips are crossfaded and can be scrubbed, slowed or frozen (e.g. holding a jump shot at its set point).
 */
UCLASS(Transient, NotBlueprintable)
class HEATCHECK_API UHCAnimInstance : public UAnimInstance
{
	GENERATED_BODY()
public:
	/** Switch to Seq. If it is already playing (and bRestart is false) only rate/loop are updated. */
	void Play(UAnimSequence* Seq, bool bLoop, float Rate = 1.f, float BlendTime = 0.15f, float StartTime = 0.f, bool bRestart = false);
	void SetRate(float InRate) { Cur.Rate = InRate; }
	void SetTime(float InTime) { Cur.Time = InTime; }
	float GetTime() const { return Cur.Time; }
	float GetLength() const;
	float GetNormalizedTime() const;
	bool IsPlaying(const UAnimSequence* Seq) const { return Cur.Seq == Seq; }
	bool IsFinished() const;
	UAnimSequence* GetCurrent() const { return Cur.Seq; }

	float HeadScale = 1.f;

protected:
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;
	virtual void NativeUpdateAnimation(float DeltaSeconds) override;

	struct FSlot
	{
		UAnimSequence* Seq = nullptr;
		float Time = 0.f;
		float Rate = 1.f;
		bool bLoop = true;
	};
	FSlot Cur;
	FSlot Prev;
	float BlendAlpha = 1.f;
	float BlendDuration = 0.15f;

	/** Keep the sequences referenced for GC. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UAnimSequence>> Referenced;

	friend struct FHCAnimProxy;
};
