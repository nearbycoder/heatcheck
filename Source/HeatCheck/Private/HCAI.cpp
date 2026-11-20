// CPU player brains. Every non-human player runs this each frame and writes into its FHCInput
// (movement / turbo) or calls actions directly (shots, passes, steals, shoves, blocks).
#include "HCGameMode.h"
#include "HeatCheck.h"
#include "HCBall.h"
#include "HCHoop.h"
#include "HCCharacter.h"

float AHCGameMode::AIReaction() const
{
	if (bAttract || Mode == EHCMode::Watch)
	{
		return 0.24f;
	}
	return Difficulty == EHCDifficulty::Easy ? 0.42f : Difficulty == EHCDifficulty::Normal ? 0.26f : 0.15f;
}

void AHCGameMode::AIMoveTo(AHCCharacter* C, const FVector2D& Target, float Dt, float Slow)
{
	const FVector2D D = Target - C->Planar();
	const float L = D.Size();
	if (L < 10.f)
	{
		C->Input.Move = FVector2D::ZeroVector;
		return;
	}
	const float Mag = L < Slow ? L / Slow : 1.f;
	C->Input.Move = D / L * Mag;
}

bool AHCGameMode::LaneOpen(const AHCCharacter* C, const FVector& To, float Width) const
{
	const FVector2D A = C->Planar();
	const FVector2D B(To.X, To.Y);
	const FVector2D AB = B - A;
	const float L2 = AB.SizeSquared();
	if (L2 < 1.f)
	{
		return true;
	}
	for (const AHCCharacter* O : Players)
	{
		if (O->Team == C->Team || O->IsDown())
		{
			continue;
		}
		const FVector2D P = O->Planar();
		const float T = FVector2D::DotProduct(P - A, AB) / L2;
		if (T < 0.05f || T > 1.05f)
		{
			continue;
		}
		if ((P - (A + AB * T)).Size() < Width)
		{
			return false;
		}
	}
	return true;
}

float AHCGameMode::OpenSpace(const FVector2D& P, int32 DefTeam) const
{
	float Best = 1e4f;
	for (const AHCCharacter* O : Players)
	{
		if (O->Team == DefTeam && !O->IsDown())
		{
			Best = FMath::Min(Best, FVector2D::Distance(P, O->Planar()));
		}
	}
	return Best;
}

void AHCGameMode::AIShootNow(AHCCharacter* C, FHCAIState& S)
{
	if (!C->CanAct() || !C->HasBall())
	{
		return;
	}
	const int32 H = C->AttackHoop();
	const FVector Rim = RimCenter(H);
	const float D = DistToHoop(C->GetActorLocation(), H);
	const bool bTurboOK = C->Turbo > 0.1f || C->bOnFire;
	if (S.Intent <= 0 && D < C->DunkRange() && bTurboOK && (D < 260.f || LaneOpen(C, Rim, 80.f)))
	{
		C->Input.bTurbo = true;
		C->StartDunk(false);
	}
	else if (D < 200.f)
	{
		C->StartLayup();
	}
	else
	{
		C->StartJumpShot();
		C->Input.bShootDown = true;
		float Noise = Difficulty == EHCDifficulty::Hard ? 0.035f : Difficulty == EHCDifficulty::Normal ? 0.07f : 0.12f;
		if (bAttract || Mode == EHCMode::Watch)
		{
			Noise = 0.06f;
		}
		S.ShootHold = Time + 0.2f + 0.286f + FMath::FRandRange(-Noise, Noise);
	}
	S.HoldTimer = 0.f;
	S.Intent = -1;
}

void AHCGameMode::TickAI(AHCCharacter* C, FHCAIState& S, float Dt)
{
	FHCInput& In = C->Input;
	In.Move = FVector2D::ZeroVector;
	In.bTurbo = false;
	In.ClearEdges();
	if (S.ShootHold >= 0.f && (C->State == EHCPState::ShootWindup || C->State == EHCPState::ShootAir))
	{
		In.bShootDown = Time < S.ShootHold;
	}
	else
	{
		S.ShootHold = -1.f;
		In.bShootDown = false;
	}
	if (C->IsDown() || C->IsDunking())
	{
		return;
	}
	S.Think -= Dt;
	S.SpotTimer -= Dt;

	switch (Phase)
	{
	case EHCPhase::Intro:
	case EHCPhase::QuarterEnd:
	case EHCPhase::Break:
	case EHCPhase::GameOver:
		return;

	case EHCPhase::TipOff:
		if (C == TipJumpers[C->Team].Get() && Ball->GetState() == EHCBallState::Loose && !bTipTouched)
		{
			const FVector BP = Ball->GetActorLocation();
			const FVector BV = Ball->GetVelocity();
			if (S.JumpAt < 0.f && BV.Z < 425.f && BP.Z > 230.f)
			{
				S.JumpAt = Time + FMath::FRandRange(0.025f, 0.115f);
			}
			if (S.JumpAt >= 0.f && Time >= S.JumpAt)
			{
				S.JumpAt = -1.f;
				if (C->CanAct() && !C->IsAirborne())
				{
					C->StartBlock();
				}
			}
		}
		return;

	case EHCPhase::Scored:
	case EHCPhase::Violation:
	{
		if (C->Team == InboundTeam)
		{
			const float Sign = InboundHoop == 0 ? -1.f : 1.f;
			AIMoveTo(C, FVector2D(Sign * (HC::CourtHalfLength - 380.f), (C->Slot == 0 ? -1.f : 1.f) * 220.f), Dt, 60.f);
		}
		else
		{
			const FVector R = RimCenter(AttackHoop(InboundTeam));
			AIMoveTo(C, FVector2D(R.X * 0.5f, (C->Slot == 0 ? -1.f : 1.f) * 260.f), Dt, 60.f);
		}
		return;
	}

	case EHCPhase::Inbound:
		if (C->State == EHCPState::Inbound)
		{
			S.HoldTimer += Dt;
			if (S.HoldTimer > 0.7f + FMath::FRand() * 0.6f && C->StateTime > 0.5f)
			{
				if (AHCCharacter* Mate = Teammate(C))
				{
					C->StartPass(Mate, false);
				}
			}
			return;
		}
		if (C->Team == InboundTeam)
		{
			const float Sign = InboundHoop == 0 ? -1.f : 1.f;
			AIMoveTo(C, FVector2D(Sign * (HC::CourtHalfLength - 400.f), (C->Slot == 0 ? -1.f : 1.f) * 200.f), Dt, 40.f);
			return;
		}
		AIDefense(C, S, Dt);
		return;

	case EHCPhase::Live:
		break;
	}

	AHCCharacter* Holder = Ball->GetHolder();
	const EHCBallState BS = Ball->GetState();
	if (Holder == C)
	{
		AIOffenseWithBall(C, S, Dt);
		return;
	}
	const bool bTeamBall = (Holder && Holder->Team == C->Team) ||
		(BS == EHCBallState::Pass && Ball->GetPasser() && Ball->GetPasser()->Team == C->Team);
	if (bTeamBall)
	{
		AIOffenseOffBall(C, S, Dt);
		return;
	}
	if (BS == EHCBallState::Loose || BS == EHCBallState::Shot)
	{
		AIChaseBall(C, S, Dt);
		return;
	}
	AIDefense(C, S, Dt);
}

void AHCGameMode::AIOffenseWithBall(AHCCharacter* C, FHCAIState& S, float Dt)
{
	const int32 H = C->AttackHoop();
	const FVector Rim = RimCenter(H);
	const FVector2D RimP(Rim.X, Rim.Y);
	const FVector Loc = C->GetActorLocation();
	const float D = DistToHoop(Loc, H);
	AHCCharacter* Mate = Teammate(C);
	S.HoldTimer += Dt;
	if (!C->CanAct())
	{
		return;
	}
	float DefD = 1e4f;
	NearestOpponent(C, &DefD);
	const bool bOpen = DefD > 220.f;
	const bool bTurboOK = C->Turbo > 0.15f || C->bOnFire;
	const float ClockLeft = FMath::Min(ShotClock, GameClock);

	if (S.Intent < 0)
	{
		// pick a plan for this touch based on the player's strengths
		const float PThree = FMath::Clamp((C->Def.Three - 4) * 0.08f, 0.f, 0.45f);
		const float PPull = FMath::Clamp(0.22f + (C->Def.Shoot - 5) * 0.05f, 0.05f, 0.45f);
		const float R = FMath::FRand();
		S.Intent = R < PThree ? 2 : (R < PThree + PPull ? 1 : 0);
		if (C->bOnFire && FMath::FRand() < 0.5f)
		{
			S.Intent = 2;
		}
		const FVector F3 = Hoops[H]->Facing();
		const float Ang = FMath::DegreesToRadians(FMath::FRandRange(-68.f, 68.f));
		const FVector2D Dir2(F3.X * FMath::Cos(Ang), FMath::Sin(Ang));
		const float Rad = S.Intent == 2 ? HC::ThreeRadius + 55.f : FMath::FRandRange(380.f, 520.f);
		S.IntentSpot = RimP + Dir2 * Rad;
		S.IntentSpot.Y = FMath::Clamp(S.IntentSpot.Y, -700.f, 700.f);
	}
	if (S.Think <= 0.f)
	{
		S.Think = AIReaction() * FMath::FRandRange(0.7f, 1.3f);
		if (ClockLeft < 2.2f)
		{
			AIShootNow(C, S);
			return;
		}
		// jump-shooters: fire once they reach their spot with a little room
		if (S.Intent > 0)
		{
			const float SpotD = FVector2D::Distance(C->Planar(), S.IntentSpot);
			if (SpotD < 90.f && S.HoldTimer > 0.5f && (DefD > 140.f || FMath::FRand() < 0.15f))
			{
				AIShootNow(C, S);
				return;
			}
			if (S.HoldTimer > 3.0f && SpotD > 200.f)
			{
				S.Intent = 0;   // can't get to the spot: attack the rim instead
			}
		}
		if (S.Intent == 0 && D < C->DunkRange() && bTurboOK && LaneOpen(C, Rim, 85.f) && FMath::FRand() < 0.3f + C->Def.Dunk * 0.04f)
		{
			C->Input.bTurbo = true;
			C->StartDunk(false);
			S.HoldTimer = 0.f;
			return;
		}
		if (D < 200.f && FMath::FRand() < 0.6f)
		{
			AIShootNow(C, S);
			return;
		}
		const bool bThree = IsThree(Loc, H);
		const int32 Rating = bThree ? C->Def.Three : C->Def.Shoot;
		float Want = 0.f;
		if (D < HC::ThreeRadius)
		{
			Want = bOpen ? 0.05f + Rating * 0.022f : 0.015f;
		}
		else if (D < 880.f)
		{
			Want = bOpen ? (Rating >= 7 ? 0.16f + (Rating - 7) * 0.08f : 0.03f) : 0.01f;
		}
		if (C->bOnFire && D < 900.f)
		{
			Want = Want * 2.5f + 0.1f;
		}
		else if (C->Streak >= 2)
		{
			Want *= 1.4f;
		}
		if (S.HoldTimer < 0.9f)
		{
			Want *= 0.25f;
		}
		if (ClockLeft < 6.f && D < 900.f)
		{
			Want += 0.25f;
		}
		if (FMath::FRand() < Want)
		{
			AIShootNow(C, S);
			return;
		}
		if (Mate && !Mate->IsDown() && !Mate->IsAirborne() && S.HoldTimer > 0.8f)
		{
			const float MD = DistToHoop(Mate->GetActorLocation(), H);
			const float MateOpen = OpenSpace(Mate->Planar(), 1 - C->Team);
			const float MyOpen = OpenSpace(C->Planar(), 1 - C->Team);
			float PassWant = 0.f;
			if (MD < D - 120.f && MateOpen > 180.f)
			{
				PassWant += 0.35f;
			}
			if (MyOpen < 130.f && MateOpen > 200.f)
			{
				PassWant += 0.35f;
			}
			if (S.HoldTimer > 4.5f)
			{
				PassWant += 0.4f;
			}
			if (Mate->bOnFire)
			{
				PassWant += 0.3f;
			}
			if (Mate->bHuman)
			{
				PassWant += 0.15f;
			}
			if (!LaneOpen(C, Mate->GetActorLocation(), 60.f))
			{
				PassWant *= 0.3f;
			}
			if (FMath::FRand() < PassWant)
			{
				const bool bAlley = !Mate->bHuman && MD < Mate->DunkRange() && MateOpen > 150.f && Mate->CanAct() && FMath::FRand() < 0.45f;
				C->StartPass(Mate, bAlley);
				S.HoldTimer = 0.f;
				return;
			}
		}
		S.bWantTurbo = bTurboOK && (LaneOpen(C, Rim, 110.f) || D > 950.f) && FMath::FRand() < 0.6f;
	}

	// drive toward the basket, slipping around defenders
	const FVector2D Me = C->Planar();
	const FVector F = Hoops[H]->Facing();
	FVector2D Goal = RimP + FVector2D(F.X, F.Y) * 100.f;
	if (S.Intent > 0)
	{
		Goal = S.IntentSpot;
	}
	FVector2D Dir = (Goal - Me).GetSafeNormal();
	for (const AHCCharacter* O : Players)
	{
		if (O->Team == C->Team || O->IsDown())
		{
			continue;
		}
		const FVector2D ToO = O->Planar() - Me;
		const float DO = ToO.Size();
		if (DO < 280.f && DO > 1.f)
		{
			const float Along = FVector2D::DotProduct(ToO / DO, Dir);
			if (Along > 0.2f)
			{
				const FVector2D Perp(-Dir.Y, Dir.X);
				const float Sd = FVector2D::DotProduct(ToO, Perp) > 0.f ? -1.f : 1.f;
				Dir += Perp * Sd * 1.3f * (1.f - DO / 280.f) * Along;
			}
		}
	}
	C->Input.Move = Dir.GetSafeNormal();
	if ((Goal - Me).Size() < 60.f)
	{
		C->Input.Move *= 0.2f;
	}
	C->Input.bTurbo = S.bWantTurbo;
}

void AHCGameMode::AIOffenseOffBall(AHCCharacter* C, FHCAIState& S, float Dt)
{
	const int32 H = C->AttackHoop();
	const FVector Rim = RimCenter(H);
	const FVector2D RimP(Rim.X, Rim.Y);
	const FVector F3 = Hoops[H]->Facing();
	const FVector2D F(F3.X, F3.Y);
	const FVector2D Y(0.f, 1.f);
	AHCCharacter* Holder = Ball->GetHolder();
	if (S.SpotTimer <= 0.f || (C->Planar() - S.Spot).Size() < 40.f)
	{
		S.SpotTimer = FMath::FRandRange(1.0f, 2.2f);
		const FVector2D Spots[] = {
			RimP + F * 480.f + Y * 470.f, RimP + F * 480.f - Y * 470.f, RimP + F * 760.f,
			FVector2D(RimP.X + F.X * 90.f, 630.f), FVector2D(RimP.X + F.X * 90.f, -630.f),
			RimP + F * 230.f + Y * 190.f, RimP + F * 230.f - Y * 190.f, RimP + F * 150.f };
		float Best = -1e9f;
		for (int32 i = 0; i < UE_ARRAY_COUNT(Spots); ++i)
		{
			const float Open = FMath::Min(500.f, OpenSpace(Spots[i], 1 - C->Team));
			float SpotScore = Open + FMath::FRand() * 140.f;
			if (Holder && FVector2D::Distance(Spots[i], Holder->Planar()) < 320.f)
			{
				SpotScore -= 400.f;
			}
			if (i == 7 && Holder && DistToHoop(Holder->GetActorLocation(), H) > 600.f)
			{
				SpotScore += 90.f;   // cut to the rim for an alley-oop look
			}
			if (C->Def.Three >= 8 && i <= 4)
			{
				SpotScore += 60.f;
			}
			if (SpotScore > Best)
			{
				Best = SpotScore;
				S.Spot = Spots[i];
			}
		}
	}
	AIMoveTo(C, S.Spot, Dt, 50.f);
	C->Input.bTurbo = FVector2D::Distance(C->Planar(), S.Spot) > 450.f && (C->Turbo > 0.4f || C->bOnFire);
	// clear a path for the ball handler with a well-timed shove
	if (Holder && C->CanAct() && C->ShoveCooldown <= 0.f && (C->Turbo > 0.35f || C->bOnFire))
	{
		float DD = 1e9f;
		if (AHCCharacter* Def = NearestOpponent(Holder, &DD))
		{
			if (DD < 160.f && FVector::Dist2D(Def->GetActorLocation(), C->GetActorLocation()) < 170.f
				&& FMath::FRand() < S.Aggro * 0.12f * Dt)
			{
				C->StartShove(Def);
			}
		}
	}
}

void AHCGameMode::AIDefense(AHCCharacter* C, FHCAIState& S, float Dt)
{
	AHCCharacter* Holder = Ball->GetHolder();
	const int32 DefHoop = AttackHoop(1 - C->Team);
	const FVector Rim = RimCenter(DefHoop);
	const FVector2D RimP(Rim.X, Rim.Y);
	TArray<AHCCharacter*> Opp;
	GetOpponents(C, Opp);
	if (Opp.Num() == 0)
	{
		return;
	}
	AHCCharacter* Mate = Teammate(C);
	AHCCharacter* Man = nullptr;
	if (Holder && Holder->Team != C->Team)
	{
		const bool bGuardBall = !Mate || Mate->IsDown() ||
			FVector::Dist2D(C->GetActorLocation(), Holder->GetActorLocation()) <= FVector::Dist2D(Mate->GetActorLocation(), Holder->GetActorLocation()) + 40.f;
		Man = bGuardBall ? Holder : (Opp[0] == Holder ? Opp.Last() : Opp[0]);
	}
	else
	{
		Man = Opp.IsValidIndex(C->Slot) ? Opp[C->Slot] : Opp[0];
	}
	const FVector2D ManP = Man->Planar();
	const bool bOnBall = Man == Holder;
	float Gap = bOnBall ? 105.f : 170.f + 0.12f * (Holder ? FVector2D::Distance(ManP, Holder->Planar()) : 0.f);
	Gap = FMath::Min(Gap, 0.5f * FVector2D::Distance(ManP, RimP));
	FVector2D Target = ManP + (RimP - ManP).GetSafeNormal() * Gap;
	if (!bOnBall && Holder)
	{
		Target = FMath::Lerp(Target, (ManP + Holder->Planar()) * 0.5f, 0.25f);
	}
	AIMoveTo(C, Target, Dt, 30.f);
	C->Input.bTurbo = FVector2D::Distance(C->Planar(), Target) > 260.f && (C->Turbo > 0.25f || C->bOnFire);
	if (!C->CanAct())
	{
		return;
	}
	const float DistMan = FVector2D::Distance(C->Planar(), ManP);
	const float React = AIReaction();
	float Skill = Difficulty == EHCDifficulty::Hard ? 1.5f : Difficulty == EHCDifficulty::Normal ? 1.f : 0.55f;
	if (bAttract || Mode == EHCMode::Watch)
	{
		Skill = 1.f;
	}
	if (bOnBall)
	{
		if ((Holder->IsShooting() && DistMan < 240.f) || (Holder->IsDunking() && DistMan < 450.f))
		{
			if (S.JumpAt < 0.f)
			{
				S.JumpAt = Time + React * FMath::FRandRange(0.5f, 1.3f);
			}
		}
		if (S.JumpAt >= 0.f && Time >= S.JumpAt)
		{
			S.JumpAt = -1.f;
			if (!C->IsAirborne())
			{
				C->StartBlock();
			}
			return;
		}
		if (Phase == EHCPhase::Live && DistMan < 140.f && C->StealCooldown <= 0.f && FMath::FRand() < Skill * (0.25f + C->Def.Steal * 0.04f) * Dt)
		{
			C->StartSteal();
			return;
		}
		if (Phase == EHCPhase::Live && DistMan < 175.f && C->ShoveCooldown <= 0.f && (C->Turbo > 0.3f || C->bOnFire))
		{
			const float P = S.Aggro * Skill * 0.22f * Dt * (Holder->bOnFire ? 2.5f : 1.f) * (Holder->IsShooting() ? 2.f : 1.f);
			if (FMath::FRand() < P)
			{
				C->Input.bTurbo = true;
				C->StartShove(Holder);
				return;
			}
		}
	}
	else
	{
		if (Holder && Holder->State == EHCPState::DunkAir && DistToHoop(C->GetActorLocation(), DefHoop) < 320.f && !C->IsAirborne())
		{
			if (S.JumpAt < 0.f)
			{
				S.JumpAt = Time + React * FMath::FRandRange(0.4f, 1.0f);
			}
		}
		if (S.JumpAt >= 0.f && Time >= S.JumpAt)
		{
			S.JumpAt = -1.f;
			if (!C->IsAirborne())
			{
				C->StartBlock();
			}
			return;
		}
		if (Holder && Mate && DistToHoop(Holder->GetActorLocation(), DefHoop) < 420.f
			&& FVector2D::Distance(Mate->Planar(), Holder->Planar()) > 160.f)
		{
			AIMoveTo(C, Holder->Planar() + (RimP - Holder->Planar()).GetSafeNormal() * 90.f, Dt, 20.f);
			C->Input.bTurbo = C->Turbo > 0.1f || C->bOnFire;
		}
		if (Ball->GetState() == EHCBallState::Pass && Ball->GetPassTarget() == Man)
		{
			const FVector BP = Ball->GetActorLocation();
			if (FVector::Dist2D(BP, C->GetActorLocation()) < 220.f)
			{
				AIMoveTo(C, FVector2D(BP.X, BP.Y), Dt, 5.f);
			}
		}
	}
}

void AHCGameMode::AIChaseBall(AHCCharacter* C, FHCAIState& S, float Dt)
{
	const FVector T3 = Ball->GetState() == EHCBallState::Shot ? Ball->PredictRebound() : Ball->GetActorLocation() + Ball->GetVelocity() * 0.25f;
	const FVector2D Target(T3.X, T3.Y);
	AHCCharacter* Mate = Teammate(C);
	const float MyD = FVector2D::Distance(C->Planar(), Target);
	const float MateD = (Mate && !Mate->IsDown()) ? FVector2D::Distance(Mate->Planar(), Target) : 1e9f;
	if (MyD <= MateD + 50.f)
	{
		AIMoveTo(C, Target, Dt, 10.f);
		C->Input.bTurbo = MyD > 180.f && (C->Turbo > 0.15f || C->bOnFire);
		const FVector BP = Ball->GetActorLocation();
		if (Ball->GetState() == EHCBallState::Loose && BP.Z > 235.f && BP.Z < 430.f && Ball->GetVelocity().Z < 80.f
			&& FVector::Dist2D(BP, C->GetActorLocation()) < 110.f && !C->IsAirborne() && C->CanAct() && S.JumpAt < 0.f)
		{
			S.JumpAt = Time + FMath::FRandRange(0.02f, 0.15f);
		}
		if (S.JumpAt >= 0.f && Time >= S.JumpAt)
		{
			S.JumpAt = -1.f;
			if (C->CanAct() && !C->IsAirborne())
			{
				C->StartBlock();
			}
		}
	}
	else
	{
		const FVector R = RimCenter(AttackHoop(1 - C->Team));
		AIMoveTo(C, FMath::Lerp(Target, FVector2D(R.X, R.Y), 0.45f), Dt, 40.f);
	}
}
