#include "HCPlayerController.h"
#include "HCGameMode.h"
#include "HCCameraDirector.h"
#include "Kismet/GameplayStatics.h"
#include "InputCoreTypes.h"
#include "HCCharacter.h"
#include "HCBall.h"
#include "HCAudio.h"
#include "HeatCheck.h"
#include "Misc/CommandLine.h"

AHCPlayerController::AHCPlayerController()
{
	bShowMouseCursor = false;
	bAutoManageActiveCameraTarget = false;
	PrimaryActorTick.bTickEvenWhenPaused = true;
	bShouldPerformFullTickWhenPaused = true;
}

void AHCPlayerController::BeginPlay()
{
	Super::BeginPlay();
	bAutopilot = FParse::Param(FCommandLine::Get(), TEXT("hcautopilot"));
	SetInputMode(FInputModeGameOnly());
	if (AHCGameMode* G = Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this)))
	{
		if (G->CameraDirector)
		{
			SetViewTarget(G->CameraDirector);
		}
	}
}

bool AHCPlayerController::Pressed(const FKey& K) const
{
	return WasInputKeyJustPressed(K);
}

bool AHCPlayerController::Down(const FKey& K) const
{
	return IsInputKeyDown(K);
}

bool AHCPlayerController::Released(const FKey& K) const
{
	return WasInputKeyJustReleased(K);
}

void AHCPlayerController::ReadPlayer(int32 P, FHCInput& Out, bool bAllowGamepad)
{
	FVector2D M(0.f, 0.f);
	bool bTurbo = false, bShoot = false, bShootP = false, bShootR = false, bPassP = false;
	if (P == 0)
	{
		// screen right = +X, screen up = -Y (camera looks toward -Y)
		if (Down(EKeys::D)) { M.X += 1.f; }
		if (Down(EKeys::A)) { M.X -= 1.f; }
		if (Down(EKeys::W)) { M.Y -= 1.f; }
		if (Down(EKeys::S)) { M.Y += 1.f; }
		bTurbo = Down(EKeys::L) || Down(EKeys::LeftShift);
		bShoot = Down(EKeys::J) || Down(EKeys::SpaceBar);
		bShootP = Pressed(EKeys::J) || Pressed(EKeys::SpaceBar);
		bShootR = Released(EKeys::J) || Released(EKeys::SpaceBar);
		bPassP = Pressed(EKeys::K);
		Out.bShovePressed |= Pressed(EKeys::H);
		if (bAllowGamepad)
		{
			M.X += GetInputAnalogKeyState(EKeys::Gamepad_LeftX);
			M.Y -= GetInputAnalogKeyState(EKeys::Gamepad_LeftY);
			if (Down(EKeys::Gamepad_DPad_Right)) { M.X += 1.f; }
			if (Down(EKeys::Gamepad_DPad_Left)) { M.X -= 1.f; }
			if (Down(EKeys::Gamepad_DPad_Up)) { M.Y -= 1.f; }
			if (Down(EKeys::Gamepad_DPad_Down)) { M.Y += 1.f; }
			bTurbo |= Down(EKeys::Gamepad_RightShoulder) || Down(EKeys::Gamepad_LeftShoulder) || GetInputAnalogKeyState(EKeys::Gamepad_RightTriggerAxis) > 0.3f;
			Out.bShovePressed |= Pressed(EKeys::Gamepad_FaceButton_Top);
			bShoot |= Down(EKeys::Gamepad_FaceButton_Bottom);
			bShootP |= Pressed(EKeys::Gamepad_FaceButton_Bottom);
			bShootR |= Released(EKeys::Gamepad_FaceButton_Bottom);
			bPassP |= Pressed(EKeys::Gamepad_FaceButton_Left) || Pressed(EKeys::Gamepad_FaceButton_Right);
		}
	}
	else
	{
		if (Down(EKeys::Right)) { M.X += 1.f; }
		if (Down(EKeys::Left)) { M.X -= 1.f; }
		if (Down(EKeys::Up)) { M.Y -= 1.f; }
		if (Down(EKeys::Down)) { M.Y += 1.f; }
		bTurbo = Down(EKeys::NumPadThree) || Down(EKeys::Slash) || Down(EKeys::RightShift);
		bShoot = Down(EKeys::NumPadOne) || Down(EKeys::Comma);
		bShootP = Pressed(EKeys::NumPadOne) || Pressed(EKeys::Comma);
		bShootR = Released(EKeys::NumPadOne) || Released(EKeys::Comma);
		Out.bShovePressed |= Pressed(EKeys::M) || Pressed(EKeys::NumPadZero);
		bPassP = Pressed(EKeys::NumPadTwo) || Pressed(EKeys::Period);
	}
	if (M.SizeSquared() > 1.f)
	{
		M.Normalize();
	}
	if (M.Size() < 0.18f)
	{
		M = FVector2D::ZeroVector;
	}
	Out.Move = M;
	Out.bTurbo = bTurbo;
	Out.bShootDown = bShoot;
	Out.bShootPressed |= bShootP;
	Out.bShootReleased |= bShootR;
	Out.bPassPressed |= bPassP;
}

void AHCPlayerController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);
	AHCGameMode* G = Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this));
	if (!G)
	{
		return;
	}
	if (Pressed(EKeys::F10))
	{
		ConsoleCommand(TEXT("HighResShot 1"));
	}
	if (G->Screen == EHCScreen::Title && G->Options.Page == EHCOptionsPage::Closed && Pressed(EKeys::Q))
	{
		G->QuitGame();
		return;
	}
	if (bAutopilot)
	{
		Autopilot(G, DeltaTime);
		return;
	}
	const bool bConfirm = Pressed(EKeys::Enter) || Pressed(EKeys::SpaceBar) || Pressed(EKeys::J) || Pressed(EKeys::Gamepad_FaceButton_Bottom) || Pressed(EKeys::Gamepad_Special_Right);
	const bool bBack = Pressed(EKeys::Escape) || Pressed(EKeys::BackSpace) || Pressed(EKeys::Gamepad_FaceButton_Right);
	const bool bPause = Pressed(EKeys::Escape) || Pressed(EKeys::P) || Pressed(EKeys::Gamepad_Special_Right);

	// navigation with key repeat
	auto Nav = [this, DeltaTime](int32 Slot, bool bDownNow, bool bPressedNow) -> bool
	{
		if (bPressedNow)
		{
			RepeatTimer[Slot] = 0.38f;
			return true;
		}
		if (bDownNow)
		{
			RepeatTimer[Slot] -= DeltaTime;
			if (RepeatTimer[Slot] <= 0.f)
			{
				RepeatTimer[Slot] = 0.12f;
				return true;
			}
		}
		return false;
	};
	const float LY = GetInputAnalogKeyState(EKeys::Gamepad_LeftY);
	const float LX = GetInputAnalogKeyState(EKeys::Gamepad_LeftX);
	const bool bUpN = Nav(0, Down(EKeys::W) || Down(EKeys::Up) || Down(EKeys::Gamepad_DPad_Up) || LY > 0.6f, Pressed(EKeys::W) || Pressed(EKeys::Up) || Pressed(EKeys::Gamepad_DPad_Up));
	const bool bDownN = Nav(1, Down(EKeys::S) || Down(EKeys::Down) || Down(EKeys::Gamepad_DPad_Down) || LY < -0.6f, Pressed(EKeys::S) || Pressed(EKeys::Down) || Pressed(EKeys::Gamepad_DPad_Down));
	const bool bLeftP1 = Nav(2, Down(EKeys::A) || Down(EKeys::Gamepad_DPad_Left) || LX < -0.6f, Pressed(EKeys::A) || Pressed(EKeys::Gamepad_DPad_Left));
	const bool bRightP1 = Nav(3, Down(EKeys::D) || Down(EKeys::Gamepad_DPad_Right) || LX > 0.6f, Pressed(EKeys::D) || Pressed(EKeys::Gamepad_DPad_Right));
	const bool bLeftP2 = Pressed(EKeys::Left);
	const bool bRightP2 = Pressed(EKeys::Right);

	FHCOptions& Options = G->Options;
	if (Options.Page != EHCOptionsPage::Closed)
	{
		if (bBack || Pressed(EKeys::P))
		{
			Options.Close(*G->Audio);
			G->Audio->Sfx(TEXT("S_UI_Back"), 0.6f);
		}
		else if (Pressed(EKeys::Tab) || Pressed(EKeys::Gamepad_LeftShoulder) || Pressed(EKeys::Gamepad_RightShoulder))
		{
			G->Audio->StopPreview();
			Options.Open(Options.Page == EHCOptionsPage::Graphics ? EHCOptionsPage::Sound : EHCOptionsPage::Graphics);
		}
		else if (bUpN || bDownN)
		{
			Options.Move(bDownN ? 1 : -1);
			G->Audio->Sfx(TEXT("S_UI_Move"), 0.6f);
		}
		else if (bLeftP1 || bRightP1 || bLeftP2 || bRightP2)
		{
			Options.Adjust(bLeftP1 || bLeftP2 ? -1 : 1, *G->Audio);
			G->Audio->Sfx(TEXT("S_UI_Move"), 0.6f);
		}
		else if (bConfirm) { Options.Confirm(*G->Audio); }
		return;
	}
	if (G->bPaused)
	{
		if (bUpN) { G->MenuUp(); }
		if (bDownN) { G->MenuDown(); }
		if (bConfirm) { G->MenuConfirm(0); }
		else if (bBack || bPause) { G->TogglePause(); }
		return;
	}
	if (G->InMenus())
	{
		if (bUpN) { G->MenuUp(); }
		if (bDownN) { G->MenuDown(); }
		const bool bVersus = G->Mode == EHCMode::TwoPlayerVersus && G->Screen == EHCScreen::TeamSelect;
		if (bLeftP1) { G->MenuLeft(0); }
		if (bRightP1) { G->MenuRight(0); }
		if (bLeftP2) { G->MenuLeft(bVersus ? 1 : 0); }
		if (bRightP2) { G->MenuRight(bVersus ? 1 : 0); }
		if (bConfirm) { G->MenuConfirm(0); }
		else if (bBack) { G->MenuBack(); }
		return;
	}
	if (G->Phase == EHCPhase::Break || G->Phase == EHCPhase::GameOver)
	{
		if (bConfirm) { G->MenuConfirm(0); }
	}
	if (bPause)
	{
		G->TogglePause();
		return;
	}
	ReadPlayer(0, G->HumanInput[0], true);
	ReadPlayer(1, G->HumanInput[1], false);
}

void AHCPlayerController::Autopilot(AHCGameMode* G, float Dt)
{
	AutoT += Dt;
	AutoActCooldown -= Dt;
	if (G->InMenus())
	{
		static const float MenuDelay = FParse::Param(FCommandLine::Get(), TEXT("autoshot")) ? 3.6f : 1.2f;
		if (AutoT > MenuDelay)
		{
			AutoT = 0.f;
			G->MenuConfirm(0);
		}
		return;
	}
	if (G->Phase == EHCPhase::Break || G->Phase == EHCPhase::GameOver)
	{
		if (AutoT > 2.f)
		{
			AutoT = 0.f;
			G->MenuConfirm(0);
		}
		return;
	}
	if (G->Players.Num() == 0)
	{
		return;
	}
	AHCCharacter* Me = G->Players[0];
	FHCInput& Out = G->HumanInput[0];
	Out.Move = FVector2D::ZeroVector;
	Out.bTurbo = false;
	const FVector Loc = Me->GetActorLocation();
	const FVector2D Me2(Loc.X, Loc.Y);
	AHCBall* B = G->Ball;
	AHCCharacter* Holder = B ? B->GetHolder() : nullptr;
	auto Press = [&](bool bShoot)
	{
		if (AutoActCooldown <= 0.f)
		{
			if (bShoot) { Out.bShootPressed = true; } else { Out.bPassPressed = true; }
			AutoActCooldown = 0.6f;
		}
	};
	if (G->Phase == EHCPhase::TipOff)
	{
		if (B->GetState() == EHCBallState::Loose && B->GetVelocity().Z < 390.f && Me->CanAct())
		{
			Press(true);
		}
		return;
	}
	// finish a held jump shot: release near the apex like a person would
	if (AutoShootHold >= 0.f)
	{
		AutoShootHold -= Dt;
		Out.bShootDown = AutoShootHold > 0.f;
		if (!Out.bShootDown)
		{
			Out.bShootReleased = true;
			AutoShootHold = -1.f;
		}
		return;
	}
	Out.bShootDown = false;
	if (Holder == Me)
	{
		AutoHoldBall += Dt;
		const int32 H = Me->AttackHoop();
		const FVector Rim = G->RimCenter(H);
		const FVector2D To(Rim.X - Me2.X, Rim.Y - Me2.Y);
		const float D = To.Size();
		Out.Move = To.GetSafeNormal();
		Out.bTurbo = Me->Turbo > 0.15f || Me->bOnFire;
		if (Me->State == EHCPState::Inbound)
		{
			Press(false);
		}
		else if (D < Me->DunkRange() * 0.8f && Out.bTurbo)
		{
			Press(true);                               // turbo + shoot near the rim = dunk
		}
		else if (AutoHoldBall > 3.5f || G->ShotClock < 4.f)
		{
			Out.bTurbo = false;
			Out.bShootPressed = true;                  // pull up for a jumper
			Out.bShootDown = true;
			AutoShootHold = FMath::FRand() < 0.5f ? 0.05f : 0.47f;   // half taps, half held to the apex
			AutoHoldBall = 0.f;
		}
		else if (AutoHoldBall > 2.2f && FMath::FRand() < 0.01f)
		{
			Press(false);                              // swing it to the teammate
		}
		return;
	}
	AutoHoldBall = 0.f;
	if (Holder && Holder->Team == Me->Team)
	{
		const FVector Rim = G->RimCenter(Me->AttackHoop());
		const FVector2D Spot(Rim.X * 0.75f, -250.f);
		Out.Move = (Spot - Me2).GetSafeNormal() * FMath::Min(1.f, (Spot - Me2).Size() / 80.f);
		if (FMath::FRand() < 0.01f)
		{
			Press(false);                              // call for the ball
		}
		return;
	}
	if (Holder)
	{
		const FVector HL = Holder->GetActorLocation();
		const FVector2D To(HL.X - Me2.X, HL.Y - Me2.Y);
		Out.Move = To.GetSafeNormal() * FMath::Min(1.f, To.Size() / 60.f);
		if (To.Size() < 150.f)
		{
			if (Holder->IsShooting())
			{
				Press(true);                           // jump to block
			}
			else if (FMath::FRand() < 0.03f)
			{
				if (AutoActCooldown <= 0.f && FMath::FRand() < 0.4f)
				{
					Out.bShovePressed = true;
					Out.bTurbo = FMath::RandBool();
					AutoActCooldown = 0.6f;
				}
				else
				{
					Press(false);
				}
			}
		}
		return;
	}
	if (B)
	{
		const FVector BL = B->GetActorLocation();
		Out.Move = FVector2D(BL.X - Me2.X, BL.Y - Me2.Y).GetSafeNormal();
		Out.bTurbo = true;
	}
}
