// Gameplay event handlers: shots, dunks, passes, steals, shoves, scoring and the heat / fire system.
#include "HCGameMode.h"
#include "HeatCheck.h"
#include "HCBall.h"
#include "HCHoop.h"
#include "HCArena.h"
#include "HCCharacter.h"
#include "HCCameraDirector.h"
#include "HCAudio.h"
#include "GameFramework/CharacterMovementComponent.h"

#define HC_EVENT(Fmt, ...) UE_LOG(LogHeatCheck, Display, TEXT("EVENT [Q%d %5.1f] " Fmt), Quarter, GameClock, ##__VA_ARGS__)

float AHCGameMode::CpuBias(int32 Team) const
{
	if (bAttract || Mode == EHCMode::Watch)
	{
		return 0.f;
	}
	const bool bHumanTeam = IsHumanTeam(Team);
	const int32 Diff = Score[Team] - Score[1 - Team];
	float B = 0.f;
	if (!bHumanTeam)
	{
		B += Difficulty == EHCDifficulty::Easy ? -0.07f : Difficulty == EHCDifficulty::Normal ? -0.01f : 0.04f;
		// arcade catch-up: the CPU finds a little extra when it falls behind
		if (Diff <= -7)
		{
			B += 0.05f;
		}
		else if (Diff >= 9)
		{
			B -= 0.04f;
		}
	}
	else if (Difficulty == EHCDifficulty::Easy)
	{
		B += 0.04f;
	}
	return B;
}

float AHCGameMode::ShotChance(const AHCCharacter* Shooter, float Quality, bool bLayup, bool bThree, float Dist) const
{
	float P;
	if (bLayup)
	{
		P = 0.78f + (Shooter->Def.Dunk + Shooter->Def.Shoot - 10) * 0.01f;
	}
	else
	{
		if (Dist < 400.f)
		{
			P = FMath::Lerp(0.66f, 0.54f, Dist / 400.f);
		}
		else if (Dist < HC::ThreeRadius)
		{
			P = FMath::Lerp(0.54f, 0.46f, (Dist - 400.f) / (HC::ThreeRadius - 400.f));
		}
		else if (Dist < 900.f)
		{
			P = FMath::Lerp(0.42f, 0.34f, (Dist - HC::ThreeRadius) / (900.f - HC::ThreeRadius));
		}
		else
		{
			P = FMath::Lerp(0.30f, 0.04f, FMath::Clamp((Dist - 900.f) / 650.f, 0.f, 1.f));
		}
		// long heaves only get a fraction of the skill / timing / fire bonuses
		const float K = FMath::Clamp(1.f - (Dist - 900.f) / 600.f, 0.2f, 1.f);
		const int32 Rating = bThree ? Shooter->Def.Three : Shooter->Def.Shoot;
		P += K * (Rating - 5) * (bThree ? 0.025f : 0.02f);
		P += FMath::Lerp(-0.22f, 0.12f * K, Quality);
		if (Shooter->bOnFire)
		{
			P += 0.28f * K - 0.28f;   // offsets the full fire bonus added below
		}
	}
	float DD = 1e9f;
	if (const AHCCharacter* Dfd = NearestOpponent(Shooter, &DD))
	{
		if (DD < 170.f)
		{
			const float C = 1.f - DD / 170.f;
			P -= C * (Dfd->IsAirborne() ? 0.26f : 0.15f);
		}
	}
	if (Shooter->bOnFire)
	{
		P += 0.28f;
	}
	else if (Shooter->Streak >= 2)
	{
		P += 0.05f;
	}
	if (Quarter >= 4 && GameClock < 12.f && FMath::Abs(Score[0] - Score[1]) <= 5)
	{
		P += (Shooter->Def.Clutch - 5) * 0.02f;
	}
	P += CpuBias(Shooter->Team);
	return FMath::Clamp(P, 0.03f, bLayup ? 0.95f : 0.93f);
}

void AHCGameMode::ReleaseShot(AHCCharacter* Shooter, float Quality, bool bLayup)
{
	if (!Shooter || !Shooter->HasBall())
	{
		return;
	}
	const int32 Hoop = AttackHoop(Shooter->Team);
	const FVector Rim = RimCenter(Hoop);
	const FVector Loc = Shooter->GetActorLocation();
	const float Dist = DistToHoop(Loc, Hoop);
	const bool bThree = !bLayup && IsThree(Loc, Hoop);
	const int32 Points = bThree ? 3 : 2;
	const float Chance = ShotChance(Shooter, Quality, bLayup, bThree, Dist);
	const bool bMake = FMath::FRand() < Chance;
	const float Flight = bLayup ? 0.55f : FMath::Clamp(0.78f + Dist / 1500.f, 0.82f, 1.55f);
	const FVector Dir = (Rim - Loc).GetSafeNormal2D();
	const FVector Side(-Dir.Y, Dir.X, 0.f);
	FVector Target;
	if (bMake)
	{
		Target = Rim + Dir * FMath::FRandRange(-2.f, 4.f) + Side * FMath::FRandRange(-3.f, 3.f) + FVector(0, 0, 3.f);
	}
	else
	{
		const float R = FMath::FRand();
		const float Edge = HC::RimRadius + FMath::FRandRange(3.f, 9.f);
		if (Quality < 0.15f && !bLayup && FMath::FRand() < 0.3f)
		{
			Target = Rim - Dir * 75.f - FVector(0, 0, 50.f);   // air ball
		}
		else if (R < 0.45f)
		{
			Target = Rim - Dir * Edge + Side * FMath::FRandRange(-8.f, 8.f) + FVector(0, 0, 8.f);   // front rim
		}
		else if (R < 0.8f)
		{
			Target = Rim + Dir * Edge + Side * FMath::FRandRange(-8.f, 8.f) + FVector(0, 0, 8.f);   // back rim
		}
		else
		{
			Target = Rim + Side * (FMath::RandBool() ? Edge : -Edge) + FVector(0, 0, 8.f);           // side
		}
	}
	Ball->LaunchShot(Shooter, Hoop, Points, bMake, Shooter->bOnFire, Flight, Target);
	Shooter->Stats.FGA++;
	if (bThree)
	{
		Shooter->Stats.TPA++;
	}
	HC_EVENT("%s shoots %s from %.0f cm (q=%.2f p=%.2f) -> %s", *Shooter->Def.Last, bLayup ? TEXT("layup") : (bThree ? TEXT("3PT") : TEXT("2PT")),
		Dist, Quality, Chance, bMake ? TEXT("MAKE") : TEXT("miss"));
	if (Audio)
	{
		Audio->Sfx(TEXT("S_Pass"), 0.35f, 0.8f);
	}
}

void AHCGameMode::DunkTakeoff(AHCCharacter* Dunker)
{
	if (Audio)
	{
		Audio->SfxVariant(TEXT("S_Squeak"), 4, 0.6f);
		Audio->Sfx(TEXT("S_CrowdOoh"), 0.55f);
	}
	if (Arena)
	{
		Arena->Excite(0.6f);
	}
}

void AHCGameMode::DunkSlam(AHCCharacter* Dunker)
{
	const int32 Hoop = AttackHoop(Dunker->Team);
	if (Dunker->bDunkBlocked || !Dunker->HasBall())
	{
		if (Hoops[Hoop])
		{
			Hoops[Hoop]->Shake(4.f);
		}
		if (Audio)
		{
			Audio->Sfx(TEXT("S_RimHit_01"), 0.7f);
		}
		return;
	}
	// a defender meeting the dunker at the rim can stuff it
	float StuffChance = 0.f;
	AHCCharacter* Stuffer = nullptr;
	const FVector RimC = RimCenter(Hoop);
	for (AHCCharacter* O : Players)
	{
		if (O->Team == Dunker->Team || O->State != EHCPState::Block || !O->IsAirborne() || O->bBlockAttempted)
		{
			continue;
		}
		const float DR = FVector::Dist2D(O->GetActorLocation(), RimC);
		const float HandDistance = FMath::Min(FVector::Dist(O->BoneLocation(TEXT("hand_l")), RimC),
			FVector::Dist(O->BoneLocation(TEXT("hand_r")), RimC));
		if (DR < 140.f && HandDistance < 65.f)
		{
			const float C = (1.f - DR / 180.f) * (0.5f + (O->Def.Block - Dunker->Def.Dunk) * 0.05f + (O->bOnFire ? 0.2f : 0.f));
			if (C > StuffChance)
			{
				StuffChance = C;
				Stuffer = O;
			}
		}
	}
	if (Dunker->bOnFire)
	{
		StuffChance *= 0.4f;
	}
	if (Stuffer)
	{
		Stuffer->bBlockAttempted = true;
	}
	if (Stuffer && FMath::FRand() < StuffChance)
	{
		Dunker->bDunkBlocked = true;
		Ball->Deflect((RimC - Stuffer->GetActorLocation()).GetSafeNormal2D() * -450.f + FVector(0, 0, 250.f), Stuffer);
		Stuffer->Stats.Blocks++;
		Dunker->Stats.FGA++;
		Hoops[Hoop]->Shake(6.f);
		HC_EVENT("STUFFED %s at the rim by %s", *Dunker->Def.Last, *Stuffer->Def.Last);
		Popup(TEXT("STUFFED!"), FLinearColor(0.3f, 0.8f, 1.f), 1.25f);
		if (Audio)
		{
			Audio->Sfx(TEXT("S_Block"), 1.f);
			Audio->Sfx(TEXT("S_RimHit_02"), 0.8f);
			Audio->VoiceVariant(TEXT("VO_Block"), 3, 3);
			Audio->Sfx(TEXT("S_CrowdOoh"), 0.9f);
		}
		if (Arena)
		{
			Arena->Excite(0.9f);
		}
		return;
	}
	Ball->DunkThrough(Hoop);
	Dunker->Stats.Dunks++;
	Hoops[Hoop]->Shake(11.f);
	Hoops[Hoop]->Swish(1.4f);
	if (Dunker->bOnFire)
	{
		Hoops[Hoop]->SetNetFire(4.f);
		Hoops[Hoop]->FlashGlass();
	}
	if (CameraDirector)
	{
		CameraDirector->Shake(1.f);
	}
	if (Arena)
	{
		Arena->Excite(1.f);
		Arena->Flash(1.f);
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_DunkSlam"), 1.f);
		Audio->Sfx(TEXT("S_CrowdBigCheer"), 0.9f);
	}
	OnBallScored(Hoop, Dunker, 2, true);
}

void AHCGameMode::ReleasePass(AHCCharacter* From, AHCCharacter* To, bool bAlley)
{
	if (!From || !To || !From->HasBall())
	{
		return;
	}
	FVector AlleyPoint = FVector::ZeroVector;
	if (bAlley && To->CanAct() && !To->IsAirborne())
	{
		const int32 Hoop = AttackHoop(To->Team);
		const FVector Rim = RimCenter(Hoop);
		const FVector Approach = (Rim - To->GetActorLocation()).GetSafeNormal2D();
		AlleyPoint = Rim - Approach * 70.f + FVector(0, 0, 55.f);
		To->StartDunk(true);
		HC_EVENT("Alley-oop lob %s -> %s", *From->Def.Last, *To->Def.Last);
	}
	else
	{
		bAlley = false;
	}
	Ball->LaunchPass(From, To, bAlley, AlleyPoint);
	LastPasser = From;
	LastPassTime = Time;
	if (Phase == EHCPhase::Inbound && From->State == EHCPState::Pass)
	{
		// inbounder steps back onto the court after the pass
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_Pass"), 0.6f);
	}
}

void AHCGameMode::ResolveShove(AHCCharacter* Shover, AHCCharacter* Target)
{
	if (!Target || Phase != EHCPhase::Live)
	{
		return;
	}
	const bool bHadBall = Target->HasBall();
	const bool bHard = Shover->bPowerShove;
	const FVector Dir = (Target->GetActorLocation() - Shover->GetActorLocation()).GetSafeNormal2D();
	const float Speed = (bHard ? 450.f : 310.f) + (Shover->Def.Power - Target->Def.Power) * 9.f;
	Target->TakeShove(Dir, Speed, bHard);
	Shover->Stats.Shoves++;
	if (bHadBall)
	{
		Ball->SetLoose(Dir * 260.f + FVector(FMath::FRandRange(-100.f, 100.f), FMath::FRandRange(-100.f, 100.f), 330.f), Target);
	}
	HC_EVENT("SHOVE %s %s %s%s", *Shover->Def.Last, bHard ? TEXT("knocks down") : TEXT("pushes back"), *Target->Def.Last, bHadBall ? TEXT(" (ball loose)") : TEXT(""));
	if (Audio)
	{
		Audio->Sfx(TEXT("S_Shove"), 0.9f);
		if (bHard)
		{
			Audio->Sfx(TEXT("S_Fall"), 0.8f);
		}
		if (bHadBall || FMath::FRand() < 0.35f)
		{
			Audio->VoiceVariant(TEXT("VO_Shove"), 2, 1);
		}
		Audio->Sfx(TEXT("S_CrowdOoh"), 0.6f);
	}
	if (Arena)
	{
		Arena->Excite(0.5f);
	}
	if (CameraDirector)
	{
		CameraDirector->Shake(0.35f);
	}
	if (bHadBall)
	{
		Popup(TEXT("SHOVED!"), FLinearColor(1.f, 0.55f, 0.15f), 0.9f);
	}
}

void AHCGameMode::ResolveSteal(AHCCharacter* Stealer)
{
	AHCCharacter* H = Ball->GetHolder();
	if (!Stealer || !H || H->Team == Stealer->Team || !IsPlayLive() || H->State == EHCPState::Inbound)
	{
		return;
	}
	const FVector ToH = H->GetActorLocation() - Stealer->GetActorLocation();
	const float D = ToH.Size2D();
	if (D > 140.f || FMath::Abs(ToH.Z) > 70.f || H->IsDunking())
	{
		return;
	}
	const float Facing = FVector::DotProduct(Stealer->GetActorForwardVector(), ToH.GetSafeNormal2D());
	if (Facing < 0.15f)
	{
		return;
	}
	float Chance = 0.15f + (Stealer->Def.Steal - 5) * 0.025f - (H->Def.Pass - 5) * 0.015f;
	if (H->Input.bTurbo)
	{
		Chance += 0.07f;
	}
	if (H->IsShooting() || H->IsDunking())
	{
		Chance -= 0.12f;
	}
	if (FVector::Dist(Ball->GetActorLocation(), Stealer->HandsCenter()) < 75.f)
	{
		Chance += 0.15f;
	}
	if (Stealer->bOnFire)
	{
		Chance += 0.1f;
	}
	Chance += CpuBias(Stealer->Team) * 0.6f;
	if (FMath::FRand() < Chance)
	{
		Stealer->Stats.Steals++;
		HC_EVENT("STEAL %s from %s", *Stealer->Def.Last, *H->Def.Last);
		if (H->IsShooting())
		{
			H->ResetForPlay();
		}
		if (FMath::FRand() < 0.55f)
		{
			GiveBall(Stealer);
		}
		else
		{
			Ball->SetLoose((Stealer->GetActorLocation() - H->GetActorLocation()).GetSafeNormal2D() * 280.f + FVector(0, 0, 160.f), Stealer);
		}
		Popup(TEXT("STEAL!"), FLinearColor(0.4f, 1.f, 0.5f), 0.95f);
		if (Audio)
		{
			Audio->Sfx(TEXT("S_Steal"), 0.9f);
			Audio->VoiceVariant(TEXT("VO_Steal"), 2, 1);
		}
		if (Arena)
		{
			Arena->Excite(0.45f);
		}
	}
	else if (Audio)
	{
		Audio->Sfx(TEXT("S_Steal"), 0.25f, 1.3f);
	}
}

void AHCGameMode::RequestPass(AHCCharacter* Holder, AHCCharacter* To)
{
	if (!Holder || Holder->bHuman || !Holder->CanAct() || !Holder->HasBall())
	{
		return;
	}
	const int32 Hoop = AttackHoop(To->Team);
	const bool bAlley = To->Input.bTurbo && DistToHoop(To->GetActorLocation(), Hoop) < To->DunkRange() + 60.f && To->CanAct();
	Holder->StartPass(To, bAlley);
}

void AHCGameMode::RequestShot(AHCCharacter* Holder)
{
	if (!Holder || Holder->bHuman || !Holder->CanAct() || !Holder->HasBall())
	{
		return;
	}
	const int32 Idx = Players.IndexOfByKey(Holder);
	if (Idx != INDEX_NONE)
	{
		AIShootNow(Holder, AI[Idx]);
	}
}

void AHCGameMode::OnJump(AHCCharacter* C)
{
	if (Audio)
	{
		Audio->SfxVariant(TEXT("S_Squeak"), 4, 0.3f, 0.1f);
	}
}

void AHCGameMode::UpdateHeat(AHCCharacter* Scorer, int32 Points, bool bDunk, bool bThree, bool bGoaltend)
{
	// the other team's streaks end and their fire goes out
	for (AHCCharacter* P : Players)
	{
		if (P->Team != Scorer->Team)
		{
			if (P->bOnFire)
			{
				P->SetFire(false);
				HC_EVENT("%s's fire is out", *P->Def.Last);
				Popup(TEXT("FIRE'S OUT"), FLinearColor(0.5f, 0.75f, 1.f), 0.8f, P->Def.Last.ToUpper(), 1.5f);
				if (Audio)
				{
					Audio->Voice(TEXT("VO_FireOut"), 2);
				}
			}
			P->Streak = 0;
			P->FireMakes = 0;
		}
	}
	Scorer->Streak++;
	if (Scorer->bOnFire)
	{
		Scorer->FireMakes++;
		if (Scorer->FireMakes >= 4)
		{
			Scorer->SetFire(false);
			Scorer->Streak = 0;
			Scorer->FireMakes = 0;
			HC_EVENT("%s cools off after 4 fire baskets", *Scorer->Def.Last);
			Popup(TEXT("COOLED OFF"), FLinearColor(0.5f, 0.75f, 1.f), 0.8f, Scorer->Def.Last.ToUpper(), 1.5f);
		}
	}
	else if (Scorer->Streak == 2)
	{
		HC_EVENT("%s is heating up", *Scorer->Def.Last);
		Popup(TEXT("HEATING UP!"), FLinearColor(1.f, 0.62f, 0.1f), 1.0f, Scorer->Def.Last.ToUpper(), 2.f);
		if (Audio)
		{
			Audio->VoiceVariant(TEXT("VO_Warm"), 2, 2);
		}
	}
	else if (Scorer->Streak >= 3)
	{
		Scorer->SetFire(true);
		Scorer->FireMakes = 0;
		HC_EVENT("%s is ON FIRE", *Scorer->Def.Last);
		Popup(TEXT("ON FIRE!"), FLinearColor(1.f, 0.32f, 0.04f), 1.35f, Scorer->Def.Last.ToUpper(), 2.6f);
		if (Audio)
		{
			Audio->Sfx(TEXT("S_FireIgnite"), 1.f);
			Audio->VoiceVariant(TEXT("VO_Fire"), 3, 3);
		}
		if (Arena)
		{
			Arena->Excite(1.f);
			Arena->Flash(0.7f);
		}
		if (CameraDirector)
		{
			CameraDirector->Shake(0.5f);
		}
	}
}

void AHCGameMode::AnnounceScore(AHCCharacter* Scorer, int32 Points, bool bDunk)
{
	const bool bAlley = bDunk && Scorer->bAlleyDunk;
	if (bAlley)
	{
		Popup(TEXT("ALLEY-OOP!"), FLinearColor(1.f, 0.85f, 0.15f), 1.25f);
		if (Audio)
		{
			Audio->Voice(TEXT("VO_AlleyOop"), 3);
		}
		return;
	}
	if (bDunk)
	{
		static const TCHAR* Words[] = { TEXT("SLAM!"), TEXT("THROW DOWN!"), TEXT("POSTERIZED!"), TEXT("MONSTER SLAM!"), TEXT("RIM ROCKER!") };
		const int32 I = FMath::RandRange(0, 4);
		Popup(Words[I], FLinearColor(1.f, 0.45f, 0.1f), 1.3f);
		if (Audio)
		{
			Audio->Voice(FString::Printf(TEXT("VO_Dunk_%02d"), I + 1), 3);
		}
		return;
	}
	if (Points == 3)
	{
		static const TCHAR* Words[] = { TEXT("BANG! THREE!"), TEXT("SPLASH!"), TEXT("FROM DEEP!") };
		Popup(Words[FMath::RandRange(0, 2)], FLinearColor(0.35f, 0.85f, 1.f), 1.15f, TEXT("3 POINTS"));
		if (Audio)
		{
			Audio->VoiceVariant(TEXT("VO_Three"), 3, 2);
			Audio->Sfx(TEXT("S_CrowdCheer_01"), 0.8f);
		}
		return;
	}
	if (Audio)
	{
		if (FMath::FRand() < 0.35f)
		{
			Audio->VoiceVariant(TEXT("VO_Score"), 3, 1);
		}
		Audio->Sfx(FMath::RandBool() ? TEXT("S_CrowdCheer_01") : TEXT("S_CrowdCheer_02"), 0.55f);
	}
}

void AHCGameMode::OnBallScored(int32 Hoop, AHCCharacter* Shooter, int32 Points, bool bDunk)
{
	if (!Shooter || Phase != EHCPhase::Live)
	{
		return;
	}
	const int32 T = Shooter->Team;
	Score[T] += Points;
	QuarterScores[T][FMath::Clamp(Quarter - 1, 0, 7)] += Points;
	Shooter->Stats.Points += Points;
	Shooter->Stats.FGM++;
	if (Points == 3)
	{
		Shooter->Stats.TPM++;
	}
	if (bDunk)
	{
		Shooter->Stats.FGA++;
	}
	if (LastPasser.IsValid() && LastPasser->Team == T && LastPasser.Get() != Shooter && Time - LastPassTime < 4.f)
	{
		LastPasser->Stats.Assists++;
	}
	LastPasser.Reset();
	HC_EVENT("SCORE %s +%d%s -> %d - %d", *Shooter->Def.Last, Points, bDunk ? TEXT(" (DUNK)") : TEXT(""), Score[0], Score[1]);

	const bool bFire = Shooter->bOnFire || Ball->WasShotFire();
	UpdateHeat(Shooter, Points, bDunk, Points == 3, false);
	if (Hoops[Hoop])
	{
		Hoops[Hoop]->Swish(bDunk ? 1.4f : 1.f);
		if (bFire || Shooter->bOnFire)
		{
			Hoops[Hoop]->SetNetFire(3.5f);
			if (Audio)
			{
				Audio->Sfx(TEXT("S_FireBasket"), 0.9f);
			}
		}
	}
	if (Audio)
	{
		if (!bDunk)
		{
			Audio->SfxVariant(TEXT("S_Swish"), 2, 0.9f);
		}
		Audio->Sfx(TEXT("S_Score"), 0.4f);
	}
	AnnounceScore(Shooter, Points, bDunk);
	if (GameClock <= 0.f || bBuzzerPending)
	{
		bBuzzerPending = false;
		Popup(TEXT("AT THE BUZZER!"), FLinearColor(1.f, 0.9f, 0.3f), 1.2f);
		if (Audio)
		{
			Audio->Voice(TEXT("VO_Buzzer"), 3);
		}
	}
	if (Arena)
	{
		Arena->Excite(bDunk || Points == 3 || bFire ? 1.f : 0.6f);
	}
	InboundTeam = 1 - T;
	InboundHoop = Hoop;
	SetPhase(EHCPhase::Scored);
}

void AHCGameMode::OnBallRim(int32 Hoop, float Speed)
{
	if (Audio)
	{
		Audio->SfxVariant(TEXT("S_RimHit"), 3, FMath::Clamp(Speed / 500.f, 0.25f, 1.f));
	}
	if (Hoops[Hoop])
	{
		Hoops[Hoop]->Shake(FMath::Clamp(Speed / 120.f, 0.5f, 4.f));
	}
	ShotClockTeam = -1;
}

void AHCGameMode::OnBallBoard(int32 Hoop, float Speed)
{
	if (Audio)
	{
		Audio->Sfx(TEXT("S_Backboard"), FMath::Clamp(Speed / 500.f, 0.3f, 1.f));
	}
}

void AHCGameMode::OnBallBounce(float Speed)
{
	if (Audio)
	{
		Audio->SfxVariant(TEXT("S_Bounce"), 3, FMath::Clamp(Speed / 600.f, 0.15f, 0.8f), 0.08f);
	}
}

void AHCGameMode::OnBallCaught(AHCCharacter* C, AHCCharacter* PassedBy)
{
	if (!C)
	{
		return;
	}
	C->OnCaughtBall();
	if (FirstPossessionTeam < 0)
	{
		FirstPossessionTeam = C->Team;
	}
	if (C->Team != PossessionTeam)
	{
		ChangePossession(C->Team);
	}
	const int32 CI = Players.IndexOfByKey(C);
	if (CI != INDEX_NONE)
	{
		AI[CI].Intent = -1;
		AI[CI].HoldTimer = 0.f;
	}
	if (Phase == EHCPhase::Inbound)
	{
		for (AHCCharacter* P : Players)
		{
			if (P->State == EHCPState::Inbound)
			{
				P->SetInbound(false);
			}
		}
		SetPhase(EHCPhase::Live);
	}
	if (PassedBy)
	{
		LastPasser = PassedBy;
		LastPassTime = Time;
	}
}

void AHCGameMode::OnPassIntercepted(AHCCharacter* By, AHCCharacter* From)
{
	if (!By)
	{
		return;
	}
	By->Stats.Steals++;
	HC_EVENT("INTERCEPTION by %s", *By->Def.Last);
	Popup(TEXT("PICKED OFF!"), FLinearColor(0.4f, 1.f, 0.5f), 1.f);
	if (Audio)
	{
		Audio->Sfx(TEXT("S_Steal"), 0.9f);
		Audio->VoiceVariant(TEXT("VO_Steal"), 2, 1);
	}
	for (AHCCharacter* P : Players)
	{
		if (P->State == EHCPState::Inbound)
		{
			P->SetInbound(false);
		}
		if (P->bAlleyDunk && P->IsDunking() && !P->HasBall())
		{
			P->bDunkBlocked = true;
		}
	}
	OnBallCaught(By, nullptr);
	if (Phase == EHCPhase::Inbound)
	{
		SetPhase(EHCPhase::Live);
	}
}
