#include "HCGameMode.h"
#include "HeatCheck.h"
#include "HCBall.h"
#include "HCReferee.h"
#include "HCHoop.h"
#include "HCArena.h"
#include "HCCharacter.h"
#include "HCCameraDirector.h"
#include "HCAudio.h"
#include "HCHUD.h"
#include "HCPlayerController.h"
#include "Engine/World.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetSystemLibrary.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "ProfilingDebugging/CsvProfiler.h"
#include "UnrealClient.h"

#define HC_EVENT(Fmt, ...) UE_LOG(LogHeatCheck, Display, TEXT("EVENT [Q%d %5.1f] " Fmt), Quarter, GameClock, ##__VA_ARGS__)

AHCGameMode::AHCGameMode()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	PlayerControllerClass = AHCPlayerController::StaticClass();
	HUDClass = AHCHUD::StaticClass();
	DefaultPawnClass = nullptr;
	FMemory::Memzero(QuarterScores, sizeof(QuarterScores));
}

void AHCGameMode::BeginPlay()
{
	Super::BeginPlay();
	bAutoShots = FParse::Param(FCommandLine::Get(), TEXT("autoshot"));
	int32 Q = 0;
	if (FParse::Value(FCommandLine::Get(), TEXT("hcquarter="), Q) && Q > 0)
	{
		QuarterMinutes = Q;
	}
	Audio = NewObject<UHCAudio>(this);
	Options.Load();
	Audio->Init(GetWorld(), Options.Sound);
	SpawnWorld();
	ReturnToTitle();
	if (FParse::Param(FCommandLine::Get(), TEXT("hcwatch")))
	{
		Mode = EHCMode::Watch;
		Screen = EHCScreen::Game;
		bAttract = false;
		SetupTeams(false);
		StartMatch();
	}
	if (FParse::Param(FCommandLine::Get(), TEXT("hcbighead")))
	{
		bBigHeads = true;
		for (AHCCharacter* C : Players)
		{
			C->ApplyHeadScale(1.7f);
		}
	}
}

void AHCGameMode::EndPlay(const EEndPlayReason::Type Reason)
{
	Options.Save();
	if (Audio) { Audio->Shutdown(); }
	Super::EndPlay(Reason);
}

void AHCGameMode::SpawnWorld()
{
	UWorld* W = GetWorld();
	FActorSpawnParameters SP;
	SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Arena = W->SpawnActor<AHCArena>(AHCArena::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, SP);
	for (int32 i = 0; i < 2; ++i)
	{
		Hoops[i] = W->SpawnActor<AHCHoop>(AHCHoop::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, SP);
		Hoops[i]->SetIndex(i);
	}
	Referee = W->SpawnActor<AHCReferee>(AHCReferee::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, SP);
	Ball = W->SpawnActor<AHCBall>(AHCBall::StaticClass(), FVector(0, 0, 200), FRotator::ZeroRotator, SP);
	for (int32 i = 0; i < 4; ++i)
	{
		const FVector P((i < 2 ? -300.f : 300.f), (i % 2 == 0 ? -200.f : 200.f), HC::PlayerHalfHeight + 2.f);
		AHCCharacter* C = W->SpawnActor<AHCCharacter>(AHCCharacter::StaticClass(), P, FRotator::ZeroRotator, SP);
		C->AddTickPrerequisiteActor(this);
		Players.Add(C);
	}
	CameraDirector = W->SpawnActor<AHCCameraDirector>(AHCCameraDirector::StaticClass(), FVector(0, 1800, 900), FRotator::ZeroRotator, SP);
	if (APlayerController* PC = W->GetFirstPlayerController())
	{
		PC->bAutoManageActiveCameraTarget = false;
		PC->SetViewTarget(CameraDirector);
	}
}

// =============================================================================
// queries
// =============================================================================

const FHCTeamDef& AHCGameMode::TeamDef(int32 Team) const
{
	const TArray<FHCTeamDef>& T = HCRoster::Teams();
	return T[FMath::Clamp(TeamIdx[FMath::Clamp(Team, 0, 1)], 0, T.Num() - 1)];
}

AHCCharacter* AHCGameMode::Teammate(const AHCCharacter* C) const
{
	if (!C)
	{
		return nullptr;
	}
	for (AHCCharacter* P : Players)
	{
		if (P && P != C && P->Team == C->Team)
		{
			return P;
		}
	}
	return nullptr;
}

void AHCGameMode::GetOpponents(const AHCCharacter* C, TArray<AHCCharacter*>& Out) const
{
	Out.Reset();
	for (AHCCharacter* P : Players)
	{
		if (P && C && P->Team != C->Team)
		{
			Out.Add(P);
		}
	}
}

AHCCharacter* AHCGameMode::NearestOpponent(const AHCCharacter* C, float* OutDist) const
{
	AHCCharacter* Best = nullptr;
	float BestD = 1e9f;
	for (AHCCharacter* P : Players)
	{
		if (P && C && P->Team != C->Team && !P->IsDown())
		{
			const float D = FVector::Dist2D(P->GetActorLocation(), C->GetActorLocation());
			if (D < BestD)
			{
				BestD = D;
				Best = P;
			}
		}
	}
	if (OutDist)
	{
		*OutDist = BestD;
	}
	return Best;
}

int32 AHCGameMode::AttackHoop(int32 Team) const
{
	const bool bSwap = Quarter >= 3;
	const int32 H = Team == 0 ? 1 : 0;
	return bSwap ? 1 - H : H;
}

FVector AHCGameMode::RimCenter(int32 Hoop) const
{
	return FVector(Hoop == 0 ? -HC::RimX : HC::RimX, 0.f, HC::RimZ);
}

FVector AHCGameMode::HoopFloor(int32 Hoop) const
{
	return FVector(Hoop == 0 ? -HC::RimX : HC::RimX, 0.f, 0.f);
}

float AHCGameMode::DistToHoop(const FVector& Pos, int32 Hoop) const
{
	return FVector::Dist2D(Pos, HoopFloor(Hoop));
}

bool AHCGameMode::IsThree(const FVector& Pos, int32 Hoop) const
{
	const float D = DistToHoop(Pos, Hoop);
	return FMath::Abs(Pos.Y) > HC::ThreeCornerY - 2.f || D > HC::ThreeRadius + 2.f;
}

int32 AHCGameMode::HumanCount() const
{
	int32 N = 0;
	for (const AHCCharacter* C : Players)
	{
		N += (C && C->bHuman) ? 1 : 0;
	}
	return N;
}

bool AHCGameMode::IsHumanTeam(int32 Team) const
{
	for (const AHCCharacter* C : Players)
	{
		if (C && C->Team == Team && C->bHuman)
		{
			return true;
		}
	}
	return false;
}

// =============================================================================
// setup / flow
// =============================================================================

void AHCGameMode::ReturnToTitle()
{
	if (bPaused)
	{
		bPaused = false;
		UGameplayStatics::SetGamePaused(this, false);
	}
	Screen = EHCScreen::Title;
	bAttract = true;
	MenuIndex = 0;
	SetupTeams(true);
	StartMatch();
	if (Audio)
	{
		Audio->PlayMusic(TEXT("M_Title"), 0.55f);
	}
}

void AHCGameMode::SetupTeams(bool bForAttract)
{
	const int32 NumTeams = HCRoster::Teams().Num();
	if (bForAttract)
	{
		TeamIdx[0] = FMath::RandRange(0, NumTeams - 1);
		do
		{
			TeamIdx[1] = FMath::RandRange(0, NumTeams - 1);
		} while (TeamIdx[1] == TeamIdx[0] && NumTeams > 1);
	}
	for (int32 i = 0; i < Players.Num(); ++i)
	{
		const int32 Team = i / 2;
		const int32 Slot = i % 2;
		const FHCTeamDef& TD = TeamDef(Team);
		Players[i]->Setup(Team, Slot, TD, TD.Players[FMath::Min(Slot, TD.Players.Num() - 1)]);
		Players[i]->ApplyHeadScale(bBigHeads ? 1.7f : 1.f);
	}
	AssignControl();
}

void AHCGameMode::AssignControl()
{
	for (AHCCharacter* C : Players)
	{
		C->bHuman = false;
		C->HumanIndex = -1;
	}
	if (bAttract || Mode == EHCMode::Watch)
	{
		return;
	}
	Players[0]->bHuman = true;
	Players[0]->HumanIndex = 0;
	if (Mode == EHCMode::TwoPlayerCoop)
	{
		Players[1]->bHuman = true;
		Players[1]->HumanIndex = 1;
	}
	else if (Mode == EHCMode::TwoPlayerVersus)
	{
		Players[2]->bHuman = true;
		Players[2]->HumanIndex = 1;
	}
}

void AHCGameMode::ResetMatchState()
{
	Score[0] = Score[1] = 0;
	FMemory::Memzero(QuarterScores, sizeof(QuarterScores));
	Quarter = 1;
	GameClock = QuarterMinutes * 60.f;
	ShotClock = HC::ShotClockLength;
	ShotClockTeam = -1;
	PossessionTeam = -1;
	bBuzzerPending = false;
	Popups.Reset();
	WinnerText.Reset();
	for (int32 i = 0; i < 4; ++i)
	{
		AI[i] = FHCAIState();
		AI[i].Aggro = FMath::FRandRange(0.3f, 1.f);
	}
	for (AHCCharacter* C : Players)
	{
		C->Stats = FHCStats();
		C->Streak = 0;
		C->FireMakes = 0;
		C->SetFire(false);
		C->Turbo = 1.f;
	}
}

void AHCGameMode::StartMatch()
{
	ResetMatchState();
	SetPhase(EHCPhase::Intro);
	if (CameraDirector)
	{
		CameraDirector->Snap();
	}
}

void AHCGameMode::SetPhase(EHCPhase P)
{
	Phase = P;
	PhaseTime = 0.f;
	switch (P)
	{
	case EHCPhase::Intro:
		PositionForTipOff();
		if (!bAttract && Audio)
		{
			Audio->StopMusic(1.5f);
			Audio->Voice(TEXT("VO_Welcome"), 3);
		}
		break;
	case EHCPhase::TipOff:
#if CSV_PROFILER
		if (!bAttract && Quarter == 1 && FParse::Param(FCommandLine::Get(), TEXT("hcprofilematch")))
		{
			FCsvProfiler::Get()->BeginCapture();
		}
#endif
		PositionForTipOff();
		bTipTouched = false;
		break;
	case EHCPhase::Live:
		break;
	case EHCPhase::Scored:
		Ball->SetDead();
		break;
	case EHCPhase::Inbound:
		PlaceInbound();
		break;
	case EHCPhase::Violation:
		Ball->SetDead();
		break;
	case EHCPhase::QuarterEnd:
		Ball->SetDead();
		if (Audio)
		{
			Audio->Sfx(TEXT("S_Buzzer"), 0.9f);
			const bool bGameOver = Quarter >= 4 && Score[0] != Score[1];
			if (bGameOver)
			{
				Audio->Voice(TEXT("VO_FinalBuzzer"), 3);
			}
			else if (Quarter == 2)
			{
				Audio->Voice(TEXT("VO_Halftime"), 3);
			}
			else if (Quarter >= 4)
			{
				Audio->Voice(TEXT("VO_Overtime"), 3);
			}
			else
			{
				Audio->Voice(TEXT("VO_EndQuarter"), 3);
			}
		}
		HC_EVENT("Quarter end %d - %d", Score[0], Score[1]);
		break;
	case EHCPhase::Break:
		BreakTimer = 0.f;
		if (Audio && !bAttract)
		{
			Audio->PlayMusic(TEXT("M_Halftime"), 0.45f);
		}
		break;
	case EHCPhase::GameOver:
	{
		const int32 W = Score[0] > Score[1] ? 0 : 1;
		WinnerText = FString::Printf(TEXT("%s %s WIN!"), *TeamDef(W).City.ToUpper(), *TeamDef(W).Name.ToUpper());
		for (AHCCharacter* C : Players)
		{
			if (C->Team == W)
			{
				C->Celebrate();
			}
		}
		HC_EVENT("GAME OVER %d - %d", Score[0], Score[1]);
#if CSV_PROFILER
		if (!bAttract && FParse::Param(FCommandLine::Get(), TEXT("hcprofilematch")))
		{
			FCsvProfiler::Get()->EndCapture();
		}
#endif
		if (Audio && !bAttract)
		{
			Audio->PlayMusic(TEXT("M_Title"), 0.5f);
		}
		break;
	}
	}
}

void AHCGameMode::PositionForTipOff()
{
	Referee->LineUp();
	Ball->HoldForTip(Referee->PoseToss(0.f));
	// first half: team 0 lives on the -X side
	const float Side0 = AttackHoop(0) == 1 ? -1.f : 1.f;
	for (int32 t = 0; t < 2; ++t)
	{
		const float Side = t == 0 ? Side0 : -Side0;
		AHCCharacter* A = Players[t * 2];
		AHCCharacter* B = Players[t * 2 + 1];
		AHCCharacter* Jumper = (B->Def.Block + B->Def.Power >= A->Def.Block + A->Def.Power) ? B : A;
		if (A->bHuman != B->bHuman)
		{
			Jumper = A->bHuman ? A : B;
		}
		AI[t * 2].JumpAt = AI[t * 2 + 1].JumpAt = -1.f;
		AHCCharacter* Other = Jumper == A ? B : A;
		TipJumpers[t] = Jumper;
		Jumper->ResetForPlay();
		Other->ResetForPlay();
		Jumper->SetActorLocation(FVector(Side * 48.f, 0.f, HC::PlayerHalfHeight + 2.f));
		Other->SetActorLocation(FVector(Side * 430.f, (t == 0 ? -1.f : 1.f) * 280.f, HC::PlayerHalfHeight + 2.f));
		Jumper->SetActorRotation(FRotator(0.f, Side > 0 ? 180.f : 0.f, 0.f));
		Other->SetActorRotation(FRotator(0.f, Side > 0 ? 180.f : 0.f, 0.f));
		Jumper->GetCharacterMovement()->StopMovementImmediately();
		Other->GetCharacterMovement()->StopMovementImmediately();
	}
}

void AHCGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const float Dt = FMath::Min(DeltaSeconds, 0.05f);
	Time += Dt;
	PhaseTime += Dt;

	// feed input to every player (humans from the controller, the rest from the AI)
	for (int32 i = 0; i < Players.Num(); ++i)
	{
		AHCCharacter* C = Players[i];
		if (C->bHuman && C->HumanIndex >= 0)
		{
			FHCInput& H = HumanInput[C->HumanIndex];
			const bool bPrevShootDown = C->Input.bShootDown;
			C->Input.Move = H.Move;
			C->Input.bTurbo = H.bTurbo;
			C->Input.bShootDown = H.bShootDown;
			C->Input.bShootPressed = H.bShootPressed;
			C->Input.bShootReleased = H.bShootReleased || (bPrevShootDown && !H.bShootDown);
			C->Input.bPassPressed = H.bPassPressed;
			C->Input.bShovePressed = H.bShovePressed;
			H.ClearEdges();
		}
		else
		{
			TickAI(C, AI[i], Dt);
		}
	}

	TickPhase(Dt);
	Referee->TrackPlay(Dt, Ball->GetActorLocation());
	TickShotDefense(Dt);
	TickPopups(Dt);
	if (Audio)
	{
		CrowdHype = FMath::FInterpTo(CrowdHype, Arena ? Arena->Excitement : 0.2f, Dt, 2.f);
		Audio->SetCrowd(CrowdHype);
		Audio->Tick(Dt);
	}
	if (bAutoShots)
	{
		TickAutomation(Dt);
	}
	static const bool bSimExit = FParse::Param(FCommandLine::Get(), TEXT("hcsimexit"));
	if (bSimExit && Phase == EHCPhase::GameOver && PhaseTime > 0.5f)
	{
		UE_LOG(LogHeatCheck, Display, TEXT("SIM FINAL %s %d - %d %s (quarters played %d)"), *TeamDef(0).Abbr, Score[0], Score[1], *TeamDef(1).Abbr, Quarter);
		for (AHCCharacter* C : Players)
		{
			const FHCStats& St = C->Stats;
			UE_LOG(LogHeatCheck, Display, TEXT("SIM STATS %-12s T%d pts %2d fg %2d-%2d 3p %d-%d dunk %d reb %d ast %d stl %d blk %d shv %d"),
				*C->Def.Last, C->Team, St.Points, St.FGM, St.FGA, St.TPM, St.TPA, St.Dunks, St.Rebounds, St.Assists, St.Steals, St.Blocks, St.Shoves);
		}
		FGenericPlatformMisc::RequestExit(false);
	}
}

void AHCGameMode::TickPhase(float Dt)
{
	switch (Phase)
	{
	case EHCPhase::Intro:
		if (!bAttract && Audio)
		{
			if (PhaseTime - Dt < 0.9f && PhaseTime >= 0.9f)
			{
				Audio->Voice(TEXT("VO_Team_") + TeamDef(1).Abbr, 2);
			}
			if (PhaseTime - Dt < 2.4f && PhaseTime >= 2.4f)
			{
				Audio->Voice(TEXT("VO_Team_") + TeamDef(0).Abbr, 2);
			}
		}
		if (PhaseTime > (bAttract ? 1.0f : 4.2f))
		{
			SetPhase(EHCPhase::TipOff);
		}
		break;

	case EHCPhase::TipOff:
		TickTipOff(Dt);
		break;

	case EHCPhase::Live:
		TickClocks(Dt);
		TickLooseBall(Dt);
		break;

	case EHCPhase::Scored:
		if (PhaseTime > 1.7f)
		{
			if (GameClock <= 0.f)
			{
				SetPhase(EHCPhase::QuarterEnd);
			}
			else
			{
				BeginInbound(InboundTeam, InboundHoop);
			}
		}
		break;

	case EHCPhase::Inbound:
	{
		TickLooseBall(Dt);
		AHCCharacter* H = Ball->GetHolder();
		if (H && H->State == EHCPState::Inbound)
		{
			const float Limit = H->bHuman ? 4.5f : 3.0f;
			if (PhaseTime > Limit && H->CanAct() == false)
			{
				if (AHCCharacter* Mate = Teammate(H))
				{
					H->StartPass(Mate, false);
				}
			}
		}
		else if (Ball->GetState() == EHCBallState::Loose || (H && H->State != EHCPState::Inbound && H->State != EHCPState::Pass))
		{
			for (AHCCharacter* C : Players)
			{
				if (C->State == EHCPState::Inbound)
				{
					C->SetInbound(false);
				}
			}
			SetPhase(EHCPhase::Live);
		}
		break;
	}

	case EHCPhase::Violation:
		if (PhaseTime > 1.6f)
		{
			BeginInbound(InboundTeam, InboundHoop);
		}
		break;

	case EHCPhase::QuarterEnd:
		if (PhaseTime > 2.6f)
		{
			if (Quarter >= 4 && Score[0] != Score[1])
			{
				SetPhase(EHCPhase::GameOver);
			}
			else
			{
				SetPhase(EHCPhase::Break);
			}
		}
		break;

	case EHCPhase::Break:
		BreakTimer += Dt;
		if ((bAttract || Mode == EHCMode::Watch) && BreakTimer > 4.f)
		{
			StartQuarter();
		}
		else if (BreakTimer > 15.f)
		{
			StartQuarter();
		}
		break;

	case EHCPhase::GameOver:
		if (bAttract && PhaseTime > 6.f)
		{
			if (Options.Page != EHCOptionsPage::Closed) { StartMatch(); }
			else { ReturnToTitle(); }
		}
		break;
	}
}

void AHCGameMode::TickTipOff(float Dt)
{
	if (Ball->GetState() == EHCBallState::Official)
	{
		const FVector Grip = Referee->PoseToss(FMath::Min(PhaseTime, AHCReferee::ReleaseTime));
		if (PhaseTime < AHCReferee::ReleaseTime)
		{
			Ball->HoldForTip(Grip);
			return;
		}
		Ball->Toss(Grip, 535.f);
		Referee->FollowThrough();
		HC_EVENT("Referee releases tip at (%.1f, %.1f, %.1f)", Grip.X, Grip.Y, Grip.Z);
		if (Audio)
		{
			Audio->Sfx(TEXT("S_Whistle"), 0.7f);
			Audio->VoiceVariant(TEXT("VO_TipOff"), 2, 2);
		}
	}
	if (bTipTouched)
	{
		return;
	}
	const FVector BP = Ball->GetActorLocation();
	AHCCharacter* Tipper = nullptr;
	float ClosestHand = FMath::Square(HC::BallRadius + 11.f);
	// Contest the descending ball with the reaching palm.
	if (BP.Z > 220.f && Ball->IsDescending())
	{
		for (const auto& Jumper : TipJumpers)
		{
			AHCCharacter* J = Jumper.Get();
			if (!J || !J->IsAirborne())
			{
				continue;
			}
			const float Distance = FVector::DistSquared(J->BoneLocation(TEXT("grip_l")), BP);
			if (Distance < ClosestHand)
			{
				ClosestHand = Distance;
				Tipper = J;
			}
		}
	}
	if (Tipper)
	{
		const FVector To = (Teammate(Tipper)->GetActorLocation() - BP).GetSafeNormal2D();
		Ball->SetLoose(To * 520.f + FVector(0, 0, 100.f), Tipper);
		bTipTouched = true;
		FirstPossessionTeam = Tipper->Team;
		if (Audio)
		{
			Audio->Sfx(TEXT("S_Block"), 0.6f);
		}
		HC_EVENT("Tip won by team %d (%s)", Tipper->Team, *Tipper->Def.Last);
		SetPhase(EHCPhase::Live);
		return;
	}
	if (Ball->GetState() == EHCBallState::Loose && BP.Z < 140.f && Ball->GetVelocity().Z < 0.f)
	{
		bTipTouched = true;
		FirstPossessionTeam = -1; // An untouched toss is decided by the first recovery.
		SetPhase(EHCPhase::Live);
	}
}

void AHCGameMode::TickClocks(float Dt)
{
	const EHCBallState BS = Ball->GetState();
	GameClock = FMath::Max(0.f, GameClock - Dt);
	if (!bAttract && GameClock > 0.f && GameClock < 5.f)
	{
		CountdownBeep -= Dt;
		if (CountdownBeep <= 0.f && Audio)
		{
			Audio->Sfx(TEXT("S_Countdown"), 0.5f);
			CountdownBeep = 1.f;
		}
	}
	AHCCharacter* Holder = Ball->GetHolder();
	int32 Ctrl = -1;
	if (BS == EHCBallState::Held && Holder)
	{
		Ctrl = Holder->Team;
	}
	else if (BS == EHCBallState::Pass && Ball->GetPasser())
	{
		Ctrl = Ball->GetPasser()->Team;
	}
	if (Ctrl >= 0)
	{
		if (Ctrl != ShotClockTeam)
		{
			ShotClockTeam = Ctrl;
			ShotClock = HC::ShotClockLength;
		}
		ShotClock = FMath::Max(0.f, ShotClock - Dt);
		if (ShotClock <= 0.f && GameClock > 0.f && (BS == EHCBallState::Held || BS == EHCBallState::Pass))
		{
			// shot clock violation
			HC_EVENT("Shot clock violation team %d", Ctrl);
			Popup(TEXT("SHOT CLOCK!"), FLinearColor(1.f, 0.3f, 0.2f), 1.f, TEXT("VIOLATION"));
			if (Audio)
			{
				Audio->Sfx(TEXT("S_ShotClock"), 0.9f);
				Audio->Voice(TEXT("VO_ShotClock"), 2);
			}
			InboundTeam = 1 - Ctrl;
			InboundHoop = AttackHoop(Ctrl);
			ShotClockTeam = -1;
			SetPhase(EHCPhase::Violation);
			return;
		}
	}
	if (GameClock <= 0.f)
	{
		if (BS == EHCBallState::Shot)
		{
			bBuzzerPending = true;
		}
		else if (!bBuzzerPending)
		{
			SetPhase(EHCPhase::QuarterEnd);
		}
		else if (BS != EHCBallState::Shot)
		{
			// shot resolved without scoring
			bBuzzerPending = false;
			SetPhase(EHCPhase::QuarterEnd);
		}
	}
}

void AHCGameMode::TickLooseBall(float Dt)
{
	if (Ball->GetState() != EHCBallState::Loose)
	{
		return;
	}
	const FVector BP = Ball->GetActorLocation();
	AHCCharacter* Best = nullptr;
	float BestD = 1e9f;
	for (AHCCharacter* C : Players)
	{
		if (!C->CanReceiveBall() || C->IsDunking() || C->ActionLock > 0.f)
		{
			continue;
		}
		if (C->IsShooting() && C->bShotReleased && C->StateTime < 0.4f)
		{
			continue;
		}
		const float D = FVector::Dist2D(C->GetActorLocation(), BP);
		const float Reach = C->IsAirborne() ? C->GetActorLocation().Z + 150.f : 240.f;
		if (D < 64.f && BP.Z < Reach && D < BestD)
		{
			Best = C;
			BestD = D;
		}
	}
	if (Best)
	{
		const bool bRebound = Ball->HasTouchedRim() || Ball->LastShooter != nullptr;
		if (bRebound)
		{
			Best->Stats.Rebounds++;
		}
		Ball->GiveTo(Best);
		Ball->LastShooter = nullptr;
		OnBallCaught(Best, nullptr);
		if (Best->IsAirborne())
		{
			// grabbed a rebound in the air: land holding it
			Best->ActionLock = 0.2f;
		}
	}
}

void AHCGameMode::TickShotDefense(float Dt)
{
	if (Phase != EHCPhase::Live)
	{
		return;
	}
	const FVector BP = Ball->GetActorLocation();
	if (Ball->GetState() == EHCBallState::Shot)
	{
		AHCCharacter* Shooter = Ball->GetShooter();
		if (!Shooter)
		{
			return;
		}
		const FVector Rim = RimCenter(Ball->GetShotHoop());
		for (AHCCharacter* O : Players)
		{
			if (O->Team == Shooter->Team || O->State != EHCPState::Block || !O->IsAirborne())
			{
				continue;
			}
			const float HD = FMath::Min(FVector::Dist(O->BoneLocation(TEXT("hand_l")), BP), FVector::Dist(O->BoneLocation(TEXT("hand_r")), BP));
			if (HD > 38.f)
			{
				continue;
			}
			const bool bDescending = Ball->IsDescending();
			const float RimD = FVector::Dist2D(BP, Rim);
			if (bDescending && RimD < 130.f && BP.Z > Rim.Z - 5.f && !O->bOnFire)
			{
				// goaltending: the basket counts
				HC_EVENT("Goaltending by %s", *O->Def.Last);
				Popup(TEXT("GOALTENDING!"), FLinearColor(1.f, 0.85f, 0.2f), 1.f, TEXT("BASKET COUNTS"));
				if (Audio)
				{
					Audio->Sfx(TEXT("S_Whistle"), 0.8f);
					Audio->Voice(TEXT("VO_Goaltending"), 3);
				}
				Ball->Deflect(FVector(FMath::FRandRange(-200.f, 200.f), FMath::FRandRange(-200.f, 200.f), -100.f), O);
				OnBallScored(Ball->GetShotHoop(), Shooter, Ball->GetShotPoints(), false);
				return;
			}
			if ((!bDescending || O->bOnFire) && !O->bBlockAttempted)
			{
				O->bBlockAttempted = true;
				const float Chance = 0.5f + (O->Def.Block - 5) * 0.05f + (O->bOnFire ? 0.2f : 0.f);
				if (FMath::FRand() < Chance)
				{
					const FVector Away = (BP - O->GetActorLocation()).GetSafeNormal2D();
					Ball->Deflect(Away * FMath::FRandRange(380.f, 620.f) + FVector(0, 0, FMath::FRandRange(-120.f, 160.f)), O);
					O->Stats.Blocks++;
					HC_EVENT("BLOCK by %s on %s", *O->Def.Last, *Shooter->Def.Last);
					Popup(TEXT("REJECTED!"), FLinearColor(0.3f, 0.8f, 1.f), 1.1f);
					if (Audio)
					{
						Audio->Sfx(TEXT("S_Block"), 1.f);
						Audio->VoiceVariant(TEXT("VO_Block"), 3, 2);
						Audio->Sfx(TEXT("S_CrowdOoh"), 0.7f);
					}
					if (Arena)
					{
						Arena->Excite(0.75f);
					}
					if (CameraDirector)
					{
						CameraDirector->Shake(0.4f);
					}
					return;
				}
			}
		}
	}
	// dunk blocks (only early in the flight)
	for (AHCCharacter* D : Players)
	{
		if (D->State != EHCPState::DunkAir || !D->HasBall() || D->bDunkBlocked || D->StateTime > D->DunkDuration * 0.7f)
		{
			continue;
		}
		for (AHCCharacter* O : Players)
		{
			if (O->Team == D->Team || O->State != EHCPState::Block || !O->IsAirborne() || O->bBlockAttempted)
			{
				continue;
			}
			const float HD = FMath::Min(FVector::Dist(O->BoneLocation(TEXT("hand_l")), BP), FVector::Dist(O->BoneLocation(TEXT("hand_r")), BP));
			if (HD >= 50.f)
			{
				continue;
			}
			O->bBlockAttempted = true;
			if (FMath::FRand() < 0.35f + O->Def.Block * 0.03f - D->Def.Dunk * 0.02f)
			{
				D->bDunkBlocked = true;
				D->Stats.FGA++;
				const FVector Away = (BP - O->GetActorLocation()).GetSafeNormal2D();
				Ball->Deflect(Away * 500.f + FVector(0, 0, 150.f), O);
				O->Stats.Blocks++;
				HC_EVENT("DUNK BLOCKED by %s", *O->Def.Last);
				Popup(TEXT("DENIED!"), FLinearColor(0.3f, 0.8f, 1.f), 1.25f);
				if (Audio)
				{
					Audio->Sfx(TEXT("S_Block"), 1.f);
					Audio->Voice(TEXT("VO_Block_02"), 3);
					Audio->Sfx(TEXT("S_CrowdOoh"), 0.9f);
				}
				if (Arena)
				{
					Arena->Excite(1.f);
				}
				return;
			}
		}
	}
}

void AHCGameMode::GiveBall(AHCCharacter* C)
{
	Ball->GiveTo(C);
	C->OnCaughtBall();
	if (C->Team != PossessionTeam)
	{
		ChangePossession(C->Team);
	}
}

void AHCGameMode::ChangePossession(int32 Team)
{
	PossessionTeam = Team;
	ShotClockTeam = Team;
	ShotClock = HC::ShotClockLength;
	for (int32 i = 0; i < 4; ++i)
	{
		AI[i].HoldTimer = 0.f;
		AI[i].SpotTimer = 0.f;
		AI[i].Aggro = FMath::FRandRange(0.25f, 1.f);
	}
}

void AHCGameMode::BeginInbound(int32 Team, int32 Hoop)
{
	InboundTeam = Team;
	InboundHoop = Hoop;
	SetPhase(EHCPhase::Inbound);
}

void AHCGameMode::PlaceInbound()
{
	AHCCharacter* A = Players[InboundTeam * 2];
	AHCCharacter* B = Players[InboundTeam * 2 + 1];
	const float Sign = InboundHoop == 0 ? -1.f : 1.f;
	const FVector Spot(Sign * (HC::CourtHalfLength + 40.f), 150.f, HC::PlayerHalfHeight + 2.f);
	// the CPU teammate inbounds so the human gets the ball right away
	AHCCharacter* Inbounder = nullptr;
	if (A->bHuman != B->bHuman)
	{
		Inbounder = A->bHuman ? B : A;
	}
	else
	{
		Inbounder = FVector::Dist2D(A->GetActorLocation(), Spot) < FVector::Dist2D(B->GetActorLocation(), Spot) ? A : B;
	}
	AHCCharacter* Receiver = Inbounder == A ? B : A;
	for (AHCCharacter* C : Players)
	{
		if (C->State != EHCPState::Free && C->State != EHCPState::Inbound)
		{
			C->ResetForPlay();
		}
	}
	Inbounder->ResetForPlay();
	Inbounder->SetActorLocation(Spot);
	Inbounder->SetActorRotation(FRotator(0.f, Sign > 0.f ? 180.f : 0.f, 0.f));
	Inbounder->GetCharacterMovement()->StopMovementImmediately();
	// make sure the receiver is in a sensible spot (teleport only if they are far away)
	const FVector RecvSpot(Sign * (HC::CourtHalfLength - 420.f), -120.f, HC::PlayerHalfHeight + 2.f);
	if (FVector::Dist2D(Receiver->GetActorLocation(), RecvSpot) > 1500.f)
	{
		Receiver->SetActorLocation(RecvSpot);
	}
	Ball->GiveTo(Inbounder);
	Inbounder->SetInbound(true);
	if (PossessionTeam != InboundTeam)
	{
		ChangePossession(InboundTeam);
	}
	ShotClock = HC::ShotClockLength;
	ShotClockTeam = InboundTeam;
	const int32 Idx = Players.IndexOfByKey(Inbounder);
	if (Idx != INDEX_NONE)
	{
		AI[Idx].HoldTimer = 0.f;
	}
}

void AHCGameMode::PlaceForQuarterStart(int32 InTeam, int32 Hoop)
{
	const float Sign = Hoop == 0 ? -1.f : 1.f;
	for (AHCCharacter* C : Players)
	{
		C->ResetForPlay();
		const bool bOffense = C->Team == InTeam;
		const float X = bOffense ? Sign * (HC::CourtHalfLength - 500.f) : Sign * (HC::CourtHalfLength - 900.f);
		const float Y = (C->Slot == 0 ? -1.f : 1.f) * 250.f;
		C->SetActorLocation(FVector(X, Y, HC::PlayerHalfHeight + 2.f));
		C->GetCharacterMovement()->StopMovementImmediately();
	}
}

void AHCGameMode::StartQuarter()
{
	Quarter++;
	GameClock = Quarter <= 4 ? QuarterMinutes * 60.f : 60.f;
	ShotClock = HC::ShotClockLength;
	ShotClockTeam = -1;
	bBuzzerPending = false;
	if (Audio)
	{
		Audio->StopMusic(1.f);
	}
	if (Quarter > 4)
	{
		SetPhase(EHCPhase::TipOff);
		return;
	}
	// alternating possession: the tip loser starts Q2 and Q3, the tip winner Q4
	const int32 T = (Quarter == 4) ? FirstPossessionTeam : 1 - FirstPossessionTeam;
	const int32 Hoop = AttackHoop(1 - T);   // inbound under the basket they defend
	PlaceForQuarterStart(T, Hoop);
	BeginInbound(T, Hoop);
	if (CameraDirector)
	{
		CameraDirector->Snap();
	}
}

void AHCGameMode::EndQuarter()
{
	SetPhase(EHCPhase::QuarterEnd);
}

// =============================================================================
// popups / automation
// =============================================================================

void AHCGameMode::Popup(const FString& Text, const FLinearColor& Color, float Scale, const FString& Sub, float Duration)
{
	if (Popups.Num() >= 3)
	{
		Popups.RemoveAt(0);
	}
	FHCPopup& P = Popups.AddDefaulted_GetRef();
	P.Text = Text;
	P.Sub = Sub;
	P.Color = Color;
	P.Scale = Scale;
	P.Duration = Duration;
	LastEventText = Text;
}

void AHCGameMode::TickPopups(float Dt)
{
	for (int32 i = Popups.Num() - 1; i >= 0; --i)
	{
		Popups[i].Time += Dt;
		if (Popups[i].Time > Popups[i].Duration)
		{
			Popups.RemoveAt(i);
		}
	}
}

void AHCGameMode::TickAutomation(float Dt)
{
	AutoTimer += Dt;
	float Duration = 70.f;
	FParse::Value(FCommandLine::Get(), TEXT("autoshotdur="), Duration);
	float Interval = 6.f;
	FParse::Value(FCommandLine::Get(), TEXT("autoshotint="), Interval);
	const float NextShot = 3.f + AutoShotIndex * Interval;
	if (AutoTimer >= NextShot)
	{
		const FString Path = FPaths::ProjectSavedDir() / FString::Printf(TEXT("AutoShots/shot_%02d.png"), AutoShotIndex);
		FScreenshotRequest::RequestScreenshot(Path, true, false);
		UE_LOG(LogHeatCheck, Display, TEXT("AUTOSHOT %s screen=%d phase=%d score=%d-%d q=%d clock=%.1f"), *Path, (int32)Screen, (int32)Phase, Score[0], Score[1], Quarter, GameClock);
		AutoShotIndex++;
	}
	if (AutoTimer > Duration)
	{
		UE_LOG(LogHeatCheck, Display, TEXT("AUTOSHOT done. Final score %d - %d (Q%d %.1f)"), Score[0], Score[1], Quarter, GameClock);
		FGenericPlatformMisc::RequestExit(false);
		bAutoShots = false;
	}
}

// =============================================================================
// menu
// =============================================================================

static const TCHAR* ModeName(EHCMode M)
{
	switch (M)
	{
	case EHCMode::OnePlayer: return TEXT("1 PLAYER  vs  CPU");
	case EHCMode::TwoPlayerCoop: return TEXT("2 PLAYERS  CO-OP");
	case EHCMode::TwoPlayerVersus: return TEXT("2 PLAYERS  HEAD-TO-HEAD");
	default: return TEXT("CPU  vs  CPU");
	}
}

FString AHCGameMode::MenuItemText(int32 Index) const
{
	switch (Index)
	{
	case 0: return TEXT("START GAME");
	case 1: return FString::Printf(TEXT("MODE:  %s"), ModeName(Mode));
	case 2: return FString::Printf(TEXT("QUARTER LENGTH:  %d MIN"), QuarterMinutes);
	case 3: return FString::Printf(TEXT("DIFFICULTY:  %s"), Difficulty == EHCDifficulty::Easy ? TEXT("ROOKIE") : Difficulty == EHCDifficulty::Normal ? TEXT("PRO") : TEXT("LEGEND"));
	case 4: return FString::Printf(TEXT("BIG HEAD MODE:  %s"), bBigHeads ? TEXT("ON") : TEXT("OFF"));
	case 5: return TEXT("GRAPHICS");
	case 6: return TEXT("SOUND");
	case 7: return TEXT("BACK TO TITLE");
	default: return TEXT("QUIT GAME");
	}
}

FString AHCGameMode::PauseItemText(int32 Index) const
{
	switch (Index)
	{
	case 0: return TEXT("RESUME");
	case 1: return TEXT("GRAPHICS");
	case 2: return TEXT("SOUND");
	case 3: return TEXT("RESTART GAME");
	case 4: return TEXT("BACK TO TITLE");
	default: return TEXT("QUIT GAME");
	}
}

void AHCGameMode::MenuUp()
{
	if (bPaused)
	{
		PauseIndex = (PauseIndex + PauseItemCount() - 1) % PauseItemCount();
	}
	else if (Screen == EHCScreen::Menu)
	{
		MenuIndex = (MenuIndex + MenuItemCount() - 1) % MenuItemCount();
	}
	else if (Screen == EHCScreen::TeamSelect)
	{
		SelectSide = 1 - SelectSide;
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_UI_Move"), 0.6f);
	}
}

void AHCGameMode::MenuDown()
{
	if (bPaused)
	{
		PauseIndex = (PauseIndex + 1) % PauseItemCount();
	}
	else if (Screen == EHCScreen::Menu)
	{
		MenuIndex = (MenuIndex + 1) % MenuItemCount();
	}
	else if (Screen == EHCScreen::TeamSelect)
	{
		SelectSide = 1 - SelectSide;
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_UI_Move"), 0.6f);
	}
}

void AHCGameMode::MenuLeft(int32 Player)
{
	MenuRight(-1 - Player);
}

void AHCGameMode::MenuRight(int32 Player)
{
	// Player < 0 encodes "left" for player (-Player - 1)
	const int32 Dir = Player < 0 ? -1 : 1;
	const int32 P = Player < 0 ? -Player - 1 : Player;
	if (Screen == EHCScreen::Menu)
	{
		switch (MenuIndex)
		{
		case 1: Mode = (EHCMode)(((int32)Mode + 4 + Dir) % 4); break;
		case 2:
		{
			static const int32 Lens[] = { 1, 2, 3, 4, 5 };
			int32 I = 0;
			for (int32 k = 0; k < 5; ++k) { if (Lens[k] == QuarterMinutes) { I = k; } }
			QuarterMinutes = Lens[(I + 5 + Dir) % 5];
			break;
		}
		case 3: Difficulty = (EHCDifficulty)(((int32)Difficulty + 3 + Dir) % 3); break;
		case 4: bBigHeads = !bBigHeads; break;
		default: break;
		}
	}
	else if (Screen == EHCScreen::TeamSelect)
	{
		const int32 N = HCRoster::Teams().Num();
		int32 Side = SelectSide;
		if (Mode == EHCMode::TwoPlayerVersus)
		{
			Side = P;
		}
		TeamIdx[Side] = (TeamIdx[Side] + N + Dir) % N;
		if (TeamIdx[0] == TeamIdx[1])
		{
			TeamIdx[Side] = (TeamIdx[Side] + N + Dir) % N;
		}
		SetupTeams(false);
		for (AHCCharacter* C : Players)
		{
			C->bHuman = false;
		}
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_UI_Move"), 0.6f);
	}
}

void AHCGameMode::MenuConfirm(int32 Player)
{
	if (bPaused)
	{
		switch (PauseIndex)
		{
		case 0:
			TogglePause();
			break;
		case 1:
		case 2:
			Options.Open(PauseIndex == 1 ? EHCOptionsPage::Graphics : EHCOptionsPage::Sound);
			break;
		case 3:
			TogglePause();
			SetupTeams(false);
			StartMatch();
			break;
		case 4:
			ReturnToTitle();
			break;
		case 5:
			QuitGame();
			return;
		}
		if (Audio)
		{
			Audio->Sfx(TEXT("S_UI_Select"), 0.7f);
		}
		return;
	}
	switch (Screen)
	{
	case EHCScreen::Title:
		Screen = EHCScreen::Menu;
		MenuIndex = 0;
		if (Audio)
		{
			Audio->Sfx(TEXT("S_UI_Start"), 0.8f);
		}
		return;
	case EHCScreen::Menu:
		if (MenuIndex == 0)
		{
			Screen = EHCScreen::TeamSelect;
			SelectSide = 0;
			if (TeamIdx[0] == TeamIdx[1])
			{
				TeamIdx[1] = (TeamIdx[0] + 1) % HCRoster::Teams().Num();
			}
		}
		else if (MenuIndex == 5 || MenuIndex == 6)
		{
			Options.Open(MenuIndex == 5 ? EHCOptionsPage::Graphics : EHCOptionsPage::Sound);
		}
		else if (MenuIndex == 8)
		{
			QuitGame();
			return;
		}
		else if (MenuIndex == 7)
		{
			Screen = EHCScreen::Title;
		}
		else
		{
			MenuRight(0);
			return;
		}
		break;
	case EHCScreen::TeamSelect:
		Screen = EHCScreen::Game;
		bAttract = false;
		SetupTeams(false);
		StartMatch();
		if (Audio)
		{
			Audio->Sfx(TEXT("S_UI_Start"), 0.9f);
		}
		return;
	case EHCScreen::Game:
		if (Phase == EHCPhase::Break && BreakTimer > 0.6f)
		{
			StartQuarter();
		}
		else if (Phase == EHCPhase::GameOver && PhaseTime > 1.5f)
		{
			ReturnToTitle();
		}
		return;
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_UI_Select"), 0.7f);
	}
}

void AHCGameMode::MenuBack()
{
	if (bPaused)
	{
		TogglePause();
		return;
	}
	if (Screen == EHCScreen::TeamSelect)
	{
		Screen = EHCScreen::Menu;
	}
	else if (Screen == EHCScreen::Menu)
	{
		Screen = EHCScreen::Title;
	}
	if (Audio)
	{
		Audio->Sfx(TEXT("S_UI_Back"), 0.6f);
	}
}

void AHCGameMode::TogglePause()
{
	if (Screen != EHCScreen::Game || bAttract)
	{
		return;
	}
	bPaused = !bPaused;
	PauseIndex = 0;
	UGameplayStatics::SetGamePaused(this, bPaused);
}

void AHCGameMode::QuitGame()
{
	Options.Save();
	UKismetSystemLibrary::QuitGame(this, GetWorld()->GetFirstPlayerController(), EQuitPreference::Quit, false);
}
