#include "HCAnimInstance.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "AnimationRuntime.h"
#include "BonePose.h"

static float AdvanceTime(float T, float Dt, float Rate, float Len, bool bLoop)
{
	T += Dt * Rate;
	if (Len <= KINDA_SMALL_NUMBER)
	{
		return 0.f;
	}
	if (bLoop)
	{
		T = FMath::Fmod(T, Len);
		if (T < 0.f)
		{
			T += Len;
		}
	}
	else
	{
		T = FMath::Clamp(T, 0.f, Len);
	}
	return T;
}

void UHCAnimInstance::Play(UAnimSequence* Seq, bool bLoop, float Rate, float BlendTime, float StartTime, bool bRestart)
{
	if (!Seq)
	{
		return;
	}
	Referenced.AddUnique(Seq);
	if (Cur.Seq == Seq && !bRestart)
	{
		Cur.bLoop = bLoop;
		Cur.Rate = Rate;
		return;
	}
	if (Cur.Seq && BlendTime > 0.f)
	{
		Prev = Cur;
		BlendAlpha = 0.f;
		BlendDuration = BlendTime;
	}
	else
	{
		Prev = FSlot();
		BlendAlpha = 1.f;
	}
	Cur.Seq = Seq;
	Cur.Time = StartTime;
	Cur.Rate = Rate;
	Cur.bLoop = bLoop;
}

float UHCAnimInstance::GetLength() const
{
	return Cur.Seq ? Cur.Seq->GetPlayLength() : 0.f;
}

float UHCAnimInstance::GetNormalizedTime() const
{
	const float L = GetLength();
	return L > 0.f ? Cur.Time / L : 0.f;
}

bool UHCAnimInstance::IsFinished() const
{
	return Cur.Seq && !Cur.bLoop && Cur.Time >= GetLength() - KINDA_SMALL_NUMBER;
}

FAnimInstanceProxy* UHCAnimInstance::CreateAnimInstanceProxy()
{
	return new FHCAnimProxy(this);
}

void UHCAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
	delete static_cast<FHCAnimProxy*>(InProxy);
}

void UHCAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);
	if (Cur.Seq)
	{
		Cur.Time = AdvanceTime(Cur.Time, DeltaSeconds, Cur.Rate, Cur.Seq->GetPlayLength(), Cur.bLoop);
	}
	if (Prev.Seq && BlendAlpha < 1.f)
	{
		Prev.Time = AdvanceTime(Prev.Time, DeltaSeconds, Prev.Rate, Prev.Seq->GetPlayLength(), Prev.bLoop);
		BlendAlpha = FMath::Min(1.f, BlendAlpha + DeltaSeconds / FMath::Max(0.01f, BlendDuration));
		if (BlendAlpha >= 1.f)
		{
			Prev = FSlot();
		}
	}
}

void FHCAnimProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
	const UHCAnimInstance* Inst = CastChecked<UHCAnimInstance>(InAnimInstance);
	CurSeq = Inst->Cur.Seq;
	CurTime = Inst->Cur.Time;
	bCurLoop = Inst->Cur.bLoop;
	PrevSeq = Inst->Prev.Seq;
	PrevTime = Inst->Prev.Time;
	bPrevLoop = Inst->Prev.bLoop;
	// smoothstep the crossfade for a softer transition
	const float A = FMath::Clamp(Inst->BlendAlpha, 0.f, 1.f);
	Alpha = A * A * (3.f - 2.f * A);
	HeadScale = Inst->HeadScale;
}

bool FHCAnimProxy::Evaluate(FPoseContext& Output)
{
	if (!CurSeq)
	{
		Output.ResetToRefPose();
		return true;
	}
	FAnimationPoseData OutData(Output);
	CurSeq->GetAnimationPose(OutData, FAnimExtractContext(double(CurTime), false, FDeltaTimeRecord(), bCurLoop));

	if (PrevSeq && Alpha < 0.999f)
	{
		FPoseContext PrevPose(Output);
		FAnimationPoseData PrevData(PrevPose);
		PrevSeq->GetAnimationPose(PrevData, FAnimExtractContext(double(PrevTime), false, FDeltaTimeRecord(), bPrevLoop));
		FAnimationRuntime::BlendTwoPosesTogetherInPlace(OutData, PrevData, Alpha);
	}

	if (!FMath::IsNearlyEqual(HeadScale, 1.f))
	{
		const FBoneContainer& BC = Output.Pose.GetBoneContainer();
		const int32 MeshIdx = BC.GetPoseBoneIndexForBoneName(FName(TEXT("head")));
		if (MeshIdx != INDEX_NONE)
		{
			const FCompactPoseBoneIndex CIdx = BC.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIdx));
			if (CIdx != INDEX_NONE)
			{
				Output.Pose[CIdx].SetScale3D(FVector(HeadScale));
			}
		}
	}
	return true;
}
