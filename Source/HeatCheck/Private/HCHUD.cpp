#include "HCHUD.h"
#include "HCGameMode.h"
#include "HCCharacter.h"
#include "HCBall.h"
#include "Engine/Canvas.h"
#include "Engine/Font.h"
#include "Engine/Texture2D.h"
#include "CanvasItem.h"
#include "Kismet/GameplayStatics.h"
#include "Framework/Application/SlateApplication.h"
#include "Rendering/SlateRenderer.h"
#include "Fonts/FontMeasure.h"

AHCHUD::AHCHUD()
{
	PrimaryActorTick.bTickEvenWhenPaused = true;
}

void AHCHUD::BeginPlay()
{
	Super::BeginPlay();
	FontBold = LoadObject<UFont>(nullptr, TEXT("/Engine/EngineFonts/Roboto.Roboto"));
	FontRegular = FontBold;
	Logo = LoadObject<UTexture2D>(nullptr, TEXT("/Game/HeatCheck/UI/UI_Logo.UI_Logo"), nullptr, LOAD_NoWarn | LOAD_Quiet);
}

AHCGameMode* AHCHUD::GM() const
{
	return Cast<AHCGameMode>(UGameplayStatics::GetGameMode(this));
}

UTexture2D* AHCHUD::TeamLogo(int32 RosterIndex)
{
	const TArray<FHCTeamDef>& T = HCRoster::Teams();
	if (TeamLogos.Num() != T.Num())
	{
		TeamLogos.SetNum(T.Num());
	}
	if (!T.IsValidIndex(RosterIndex))
	{
		return nullptr;
	}
	if (!TeamLogos[RosterIndex])
	{
		const FString N = TEXT("UI_Team_") + T[RosterIndex].Abbr;
		TeamLogos[RosterIndex] = LoadObject<UTexture2D>(nullptr, *FString::Printf(TEXT("/Game/HeatCheck/UI/%s.%s"), *N, *N), nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
	return TeamLogos[RosterIndex];
}

// -----------------------------------------------------------------------------
// primitives
// -----------------------------------------------------------------------------

static FSlateFontInfo MakeFont(UFont* Font, float Px, bool bBold, float Outline)
{
	FSlateFontInfo Info(Font, FMath::Max(1, FMath::RoundToInt(Px * 0.75f)), bBold ? FName(TEXT("Bold")) : FName(TEXT("Regular")));
	if (Outline > 0.f)
	{
		Info.OutlineSettings.OutlineSize = FMath::Max(1, FMath::RoundToInt(Outline));
		Info.OutlineSettings.OutlineColor = FLinearColor(0.f, 0.f, 0.f, 0.9f);
	}
	return Info;
}

FVector2D AHCHUD::Measure(const FString& Str, float Size, bool bBold) const
{
	if (!FSlateApplication::IsInitialized() || !FontBold)
	{
		return FVector2D(Str.Len() * Size * UIScale * 0.55f, Size * UIScale);
	}
	const FSlateFontInfo Info = MakeFont(FontBold, Size * UIScale, bBold, 0.f);
	return FSlateApplication::Get().GetRenderer()->GetFontMeasureService()->Measure(Str, Info);
}

void AHCHUD::Text(const FString& Str, float X, float Y, float Size, const FLinearColor& Color, bool bCenter, bool bShadow, float Outline, bool bBold, float DrawScale)
{
	if (!Canvas || !FontBold)
	{
		return;
	}
	FCanvasTextItem Item(FVector2D(X, Y), FText::FromString(Str), MakeFont(FontBold, Size * UIScale, bBold, Outline * UIScale), Color);
	Item.Scale = FVector2D(DrawScale);
	Item.bCentreX = bCenter;
	if (bShadow)
	{
		Item.EnableShadow(FLinearColor(0.f, 0.f, 0.f, 0.7f), FVector2D(2.f, 2.f) * UIScale);
	}
	Item.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Item);
}

void AHCHUD::Rect(float X, float Y, float W, float H, const FLinearColor& Color)
{
	if (!Canvas)
	{
		return;
	}
	FCanvasTileItem Tile(FVector2D(X, Y), FVector2D(W, H), Color);
	Tile.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Tile);
}

void AHCHUD::Tex(UTexture2D* T, float X, float Y, float W, float H, const FLinearColor& Tint)
{
	if (!Canvas || !T || !T->GetResource())
	{
		return;
	}
	FCanvasTileItem Tile(FVector2D(X, Y), T->GetResource(), FVector2D(W, H), Tint);
	Tile.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Tile);
}

static FLinearColor TextOn(const FLinearColor& Bg)
{
	const float L = 0.2126f * Bg.R + 0.7152f * Bg.G + 0.0722f * Bg.B;
	return L > 0.35f ? FLinearColor(0.02f, 0.02f, 0.03f) : FLinearColor::White;
}

FString AHCHUD::ClockString(float Seconds) const
{
	Seconds = FMath::Max(0.f, Seconds);
	if (Seconds < 10.f)
	{
		return FString::Printf(TEXT("%.1f"), Seconds);
	}
	const int32 T = FMath::CeilToInt(Seconds);
	return FString::Printf(TEXT("%d:%02d"), T / 60, T % 60);
}

// -----------------------------------------------------------------------------
// main
// -----------------------------------------------------------------------------

void AHCHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas)
	{
		return;
	}
	UIScale = Canvas->ClipY / 1080.f;
	Time = GetWorld()->GetRealTimeSeconds();
	AHCGameMode* G = GM();
	if (!G)
	{
		return;
	}
	const bool bOptions = G->Options.Page != EHCOptionsPage::Closed;
	if (bOptions || (G->Screen == EHCScreen::Game && G->Options.bShowMeter))
	{
		UpdateFrameSample();
	}
	else
	{
		SampleStart = 0.0;
	}
	if (bOptions)
	{
		DrawOptions();
		return;
	}
	switch (G->Screen)
	{
	case EHCScreen::Title: DrawTitle(); return;
	case EHCScreen::Menu: DrawMenu(); return;
	case EHCScreen::TeamSelect: DrawTeamSelect(); return;
	default: break;
	}
	switch (G->Phase)
	{
	case EHCPhase::Intro:
		DrawIntro();
		break;
	case EHCPhase::Break:
		DrawBreak(false);
		break;
	case EHCPhase::GameOver:
		DrawBreak(true);
		break;
	default:
		DrawPlayerMarkers();
		DrawScoreboard();
		DrawPlayerCards();
		DrawShotMeter();
		DrawPopups();
		break;
	}
	if (G->bPaused)
	{
		DrawPause();
	}
	else if (G->Options.bShowMeter)
	{
		const float W = 274.f * S();
		DrawQualityMeter(Canvas->ClipX - W - 20.f * S(), 18.f * S(), W, false);
	}
}

void AHCHUD::DrawScoreboard()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX;
	const float PW = 880.f * s, PH = 92.f * s;
	const float X0 = (W - PW) * 0.5f, Y0 = 14.f * s;
	Rect(X0 - 4.f * s, Y0 - 4.f * s, PW + 8.f * s, PH + 8.f * s, FLinearColor(1.f, 0.35f, 0.05f, 0.85f));
	Rect(X0, Y0, PW, PH, FLinearColor(0.015f, 0.015f, 0.02f, 0.92f));
	for (int32 t = 0; t < 2; ++t)
	{
		const FHCTeamDef& TD = G->TeamDef(t);
		const float BW = 210.f * s;
		const float BX = t == 0 ? X0 : X0 + PW - BW;
		Rect(BX, Y0, BW, PH, FLinearColor(TD.Primary.R, TD.Primary.G, TD.Primary.B, 1.f));
		Rect(BX, Y0 + PH - 7.f * s, BW, 7.f * s, TD.Secondary);
		const FLinearColor TC = TextOn(TD.Primary);
		Text(TD.Abbr, BX + BW * 0.5f, Y0 + 6.f * s, 46.f, TC, true, false);
		Text(TD.Name.ToUpper(), BX + BW * 0.5f, Y0 + 58.f * s, 17.f, TC, true, false);
		const float SX = t == 0 ? BX + BW + 85.f * s : BX - 85.f * s;
		Text(FString::FromInt(G->Score[t]), SX, Y0 + 4.f * s, 64.f, FLinearColor::White, true, true);
		// possession arrow
		if (G->PossessionTeam == t && G->Phase == EHCPhase::Live)
		{
			const float AX = t == 0 ? BX + BW + 6.f * s : BX - 18.f * s;
			Rect(AX, Y0 + PH * 0.5f - 6.f * s, 12.f * s, 12.f * s, FLinearColor(1.f, 0.6f, 0.1f, 1.f));
		}
	}
	const FString QLabel = G->Quarter <= 4 ? FString::Printf(TEXT("QUARTER %d"), G->Quarter) : FString::Printf(TEXT("OVERTIME %d"), G->Quarter - 4);
	Text(QLabel, W * 0.5f, Y0 + 8.f * s, 20.f, FLinearColor(1.f, 0.75f, 0.2f), true, false);
	const FLinearColor ClockCol = G->GameClock < 10.f ? FLinearColor(1.f, 0.3f, 0.2f) : FLinearColor::White;
	Text(ClockString(G->GameClock), W * 0.5f, Y0 + 32.f * s, 46.f, ClockCol, true, false);
	// shot clock
	const float SCW = 76.f * s;
	const float SCX = W * 0.5f - SCW * 0.5f, SCY = Y0 + PH + 6.f * s;
	Rect(SCX, SCY, SCW, 42.f * s, FLinearColor(0.f, 0.f, 0.f, 0.85f));
	const int32 SC = FMath::CeilToInt(G->ShotClock);
	Text(FString::FromInt(SC), W * 0.5f, SCY + 2.f * s, 34.f, SC <= 5 ? FLinearColor(1.f, 0.2f, 0.15f) : FLinearColor(1.f, 0.72f, 0.1f), true, false);
}

void AHCHUD::DrawPlayerCards()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	for (int32 i = 0; i < G->Players.Num(); ++i)
	{
		AHCCharacter* C = G->Players[i];
		const int32 t = C->Team;
		const float CW = 360.f * s, CH = 62.f * s;
		const float X = t == 0 ? 22.f * s : W - 22.f * s - CW;
		const float Y = H - (22.f + (2 - C->Slot) * 70.f) * s;
		Rect(X, Y, CW, CH, FLinearColor(0.01f, 0.01f, 0.015f, 0.78f));
		Rect(X, Y, 8.f * s, CH, G->TeamDef(t).Primary);
		FString Tag = TEXT("CPU");
		FLinearColor TagCol(0.55f, 0.55f, 0.6f);
		if (C->bHuman)
		{
			Tag = C->HumanIndex == 0 ? TEXT("P1") : TEXT("P2");
			TagCol = C->HumanIndex == 0 ? FLinearColor(1.f, 0.85f, 0.1f) : FLinearColor(0.15f, 0.75f, 1.f);
		}
		Text(Tag, X + 20.f * s, Y + 6.f * s, 22.f, TagCol, false, false);
		Text(FString::Printf(TEXT("#%d %s"), C->Def.Number, *C->Def.Last.ToUpper()), X + 72.f * s, Y + 6.f * s, 22.f, FLinearColor::White, false, false);
		const FString Pts = FString::Printf(TEXT("%d PTS"), C->Stats.Points);
		Text(Pts, X + CW - 14.f * s - Measure(Pts, 16.f).X, Y + 9.f * s, 16.f, FLinearColor(0.8f, 0.8f, 0.85f), false, false);
		// turbo meter
		const float BX = X + 20.f * s, BY = Y + 40.f * s, BW = 170.f * s, BH = 12.f * s;
		Rect(BX, BY, BW, BH, FLinearColor(0.15f, 0.15f, 0.18f, 1.f));
		FLinearColor TCol = C->Turbo < 0.25f ? FLinearColor(1.f, 0.2f, 0.1f) : FLinearColor(0.3f, 1.f, 0.35f);
		if (C->bOnFire)
		{
			TCol = FLinearColor(1.f, 0.4f + 0.3f * FMath::Sin(Time * 18.f), 0.05f);
		}
		Rect(BX, BY, BW * FMath::Clamp(C->Turbo, 0.f, 1.f), BH, TCol);
		Text(TEXT("TURBO"), BX + BW + 8.f * s, BY - 4.f * s, 13.f, FLinearColor(0.7f, 0.7f, 0.75f), false, false);
		if (C->bOnFire)
		{
			const float F = 0.75f + 0.25f * FMath::Sin(Time * 14.f);
			Text(TEXT("ON FIRE"), X + CW - 108.f * s, BY - 9.f * s, 20.f, FLinearColor(1.f, 0.45f * F, 0.05f), false, true, 2.f);
		}
		else
		{
			for (int32 k = 0; k < FMath::Min(C->Streak, 2); ++k)
			{
				Rect(X + CW - 60.f * s + k * 22.f * s, BY - 1.f * s, 14.f * s, 14.f * s, FLinearColor(1.f, 0.55f, 0.1f, 1.f));
			}
		}
	}
}

void AHCHUD::DrawPlayerMarkers()
{
	AHCGameMode* G = GM();
	const float s = S();
	for (AHCCharacter* C : G->Players)
	{
		if (!C->bHuman && !C->bOnFire)
		{
			continue;
		}
		const FVector P = Project(C->GetActorLocation() + FVector(0.f, 0.f, 150.f));
		if (P.Z <= 0.f)
		{
			continue;
		}
		if (C->bHuman)
		{
			const FLinearColor Col = C->HumanIndex == 0 ? FLinearColor(1.f, 0.85f, 0.1f) : FLinearColor(0.15f, 0.75f, 1.f);
			const FString L = C->HumanIndex == 0 ? TEXT("P1") : TEXT("P2");
			Text(L, P.X, P.Y - 44.f * s, 24.f, Col, true, true, 2.f);
			for (int32 k = 0; k < 5; ++k)
			{
				const float Wd = (10.f - k * 2.f) * s;
				Rect(P.X - Wd * 0.5f, P.Y - 14.f * s + k * 2.f * s, Wd, 2.f * s, Col);
			}
		}
	}
}

void AHCHUD::DrawShotMeter()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float Now = GetWorld()->GetTimeSeconds();
	for (AHCCharacter* C : G->Players)
	{
		if (!C->bHuman || !(C->State == EHCPState::ShootAir || C->State == EHCPState::ShootWindup) || C->bShotReleased)
		{
			continue;
		}
		const FVector P = Project(C->GetActorLocation() + FVector(0.f, 0.f, 60.f));
		if (P.Z <= 0.f)
		{
			continue;
		}
		float T = 0.f;
		if (C->State == EHCPState::ShootAir)
		{
			T = (Now - C->LaunchTime) / FMath::Max(0.05f, C->ApexTime - C->LaunchTime);
		}
		const float X = P.X + 60.f * s, Y = P.Y - 60.f * s, BW = 14.f * s, BH = 110.f * s;
		Rect(X - 2.f * s, Y - 2.f * s, BW + 4.f * s, BH + 4.f * s, FLinearColor(0.f, 0.f, 0.f, 0.8f));
		// perfect window
		Rect(X, Y, BW, BH * 0.16f, FLinearColor(0.2f, 1.f, 0.3f, 0.45f));
		const float Fill = FMath::Clamp(T, 0.f, 1.2f) / 1.2f;
		const bool bGood = FMath::Abs(T - 1.f) < 0.2f;
		Rect(X, Y + BH * (1.f - Fill), BW, BH * Fill, bGood ? FLinearColor(0.3f, 1.f, 0.35f) : (T > 1.2f ? FLinearColor(1.f, 0.2f, 0.1f) : FLinearColor(1.f, 0.8f, 0.2f)));
	}
}

void AHCHUD::DrawPopups()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX;
	const bool bScore = !G->Popups.IsEmpty() && G->Phase == EHCPhase::Scored;
	float Center = W * 0.5f;
	if (bScore)
	{
		const float RimX = Project(G->RimCenter(G->InboundHoop)).X;
		Center = W * (RimX >= Center ? 0.25f : 0.75f);
	}
	for (int32 i = 0; i < G->Popups.Num(); ++i)
	{
		const FHCPopup& P = G->Popups[i];
		const float T = P.Time / P.Duration;
		const float In = FMath::Clamp(P.Time * 7.f, 0.f, 1.f);
		const float Pop = 1.f + 0.35f * (1.f - In) * (1.f - In);
		const float Alpha = FMath::Clamp((1.f - T) * 5.f, 0.f, 1.f);
		// Animate the cached glyph quads, keeping one raster size per popup style.
		const float Size = (bScore ? 62.f : 84.f) * P.Scale;
		const float HalfWidth = bScore ? FMath::Min(0.5f * W, Measure(P.Text, Size).X * Pop * 0.5f + 10.f * s) : 0.f;
		const float X = FMath::Clamp(Center, HalfWidth, W - HalfWidth);
		const float Y = (230.f + i * 110.f) * s;
		FLinearColor C = P.Color;
		C.A = Alpha;
		Text(P.Text, X, Y, Size, C, true, true, 4.f, true, Pop);
		if (!P.Sub.IsEmpty())
		{
			Text(P.Sub, X, Y + Size * Pop * 1.05f * s, 28.f, FLinearColor(1.f, 1.f, 1.f, Alpha), true, true, 2.f);
		}
	}
}

// -----------------------------------------------------------------------------
// screens
// -----------------------------------------------------------------------------

void AHCHUD::DrawControlsHint(float Y)
{
	const float W = Canvas->ClipX;
	Text(TEXT("MOVE  WASD / STICK      SHOOT  J / A      PASS - STEAL  K / X      SHOVE  H / Y      TURBO  L / SHIFT / RB"), W * 0.5f, Y, 19.f, FLinearColor(0.85f, 0.85f, 0.9f), true, true);
	Text(TEXT("TURBO + SHOOT NEAR THE RIM = DUNK      TURBO + SHOVE = KNOCKDOWN      TURBO + PASS = ALLEY-OOP      P2 SHOVE  M / NUM 0"),
		W * 0.5f, Y + 28.f * S(), 16.f, FLinearColor(1.f, 0.7f, 0.3f), true, true);
}

void AHCHUD::DrawTitle()
{
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.02f, 0.45f));
	if (Logo)
	{
		const float LW = 1150.f * s, LH = LW * 0.5f;
		Tex(Logo, (W - LW) * 0.5f, 70.f * s, LW, LH);
	}
	else
	{
		Text(TEXT("HEAT CHECK"), W * 0.5f, 220.f * s, 150.f, FLinearColor(1.f, 0.45f, 0.08f), true, true, 6.f);
		Text(TEXT("2 ON 2 ARCADE HOOPS"), W * 0.5f, 400.f * s, 40.f, FLinearColor::White, true, true, 2.f);
	}
	const float Blink = 0.55f + 0.45f * FMath::Sin(Time * 5.f);
	Text(TEXT("PRESS ENTER / START"), W * 0.5f, 700.f * s, 48.f, FLinearColor(1.f, 0.85f, 0.25f, Blink), true, true, 3.f);
	DrawControlsHint(H - 120.f * s);
	Text(TEXT("Q   QUIT GAME"), W * 0.5f, H - 46.f * s, 15.f, FLinearColor(0.6f, 0.6f, 0.65f), true, false);
}

void AHCHUD::DrawMenu()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.02f, 0.55f));
	if (Logo)
	{
		const float LW = 570.f * s, LH = LW * 0.5f;
		Tex(Logo, (W - LW) * 0.5f, 20.f * s, LW, LH);
	}
	const float PW = 860.f * s;
	const float X0 = (W - PW) * 0.5f;
	const float Y0 = 320.f * s;
	Rect(X0, Y0, PW, (G->MenuItemCount() * 68.f + 30.f) * s, FLinearColor(0.02f, 0.02f, 0.03f, 0.88f));
	for (int32 i = 0; i < G->MenuItemCount(); ++i)
	{
		const float Y = Y0 + (18.f + i * 68.f) * s;
		const bool bSel = i == G->MenuIndex;
		if (bSel)
		{
			Rect(X0 + 12.f * s, Y - 4.f * s, PW - 24.f * s, 60.f * s, FLinearColor(1.f, 0.38f, 0.05f, 0.9f));
		}
		FString Label = G->MenuItemText(i);
		if (bSel && i >= 1 && i <= 4)
		{
			Label = TEXT("<   ") + Label + TEXT("   >");
		}
		Text(Label, W * 0.5f, Y + 4.f * s, i == 0 ? 40.f : 32.f, bSel ? FLinearColor::White : FLinearColor(0.8f, 0.8f, 0.85f), true, bSel);
	}
	Text(TEXT("W/S SELECT    A/D CHANGE    ENTER CONFIRM    ESC BACK"), W * 0.5f, H - 70.f * s, 20.f, FLinearColor(0.75f, 0.75f, 0.8f), true, true);
}

void AHCHUD::DrawTeamSelect()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.02f, 0.62f));
	Text(TEXT("CHOOSE YOUR TEAMS"), W * 0.5f, 34.f * s, 56.f, FLinearColor(1.f, 0.55f, 0.1f), true, true, 3.f);
	const bool bVersus = G->Mode == EHCMode::TwoPlayerVersus;
	for (int32 Side = 0; Side < 2; ++Side)
	{
		const int32 R = G->TeamIdx[Side];
		const FHCTeamDef& TD = HCRoster::Teams()[R];
		const float PW = 760.f * s, PH = 780.f * s;
		const float X = Side == 0 ? W * 0.5f - PW - 60.f * s : W * 0.5f + 60.f * s;
		const float Y = 130.f * s;
		const bool bActive = bVersus || G->SelectSide == Side;
		Rect(X - 5.f * s, Y - 5.f * s, PW + 10.f * s, PH + 10.f * s, bActive ? FLinearColor(1.f, 0.45f, 0.05f, 0.95f) : FLinearColor(0.2f, 0.2f, 0.25f, 0.9f));
		Rect(X, Y, PW, PH, FLinearColor(0.02f, 0.02f, 0.03f, 0.92f));
		Rect(X, Y, PW, 14.f * s, TD.Primary);
		FString Who = Side == 0 ? TEXT("HOME") : TEXT("AWAY");
		if (G->Mode == EHCMode::OnePlayer)
		{
			Who = Side == 0 ? TEXT("PLAYER 1") : TEXT("CPU");
		}
		else if (G->Mode == EHCMode::TwoPlayerCoop)
		{
			Who = Side == 0 ? TEXT("P1 + P2") : TEXT("CPU");
		}
		else if (G->Mode == EHCMode::TwoPlayerVersus)
		{
			Who = Side == 0 ? TEXT("PLAYER 1") : TEXT("PLAYER 2");
		}
		Text(Who, X + PW * 0.5f, Y + 24.f * s, 26.f, FLinearColor(0.85f, 0.85f, 0.9f), true, false);
		if (UTexture2D* L = TeamLogo(R))
		{
			Tex(L, X + PW * 0.5f - 150.f * s, Y + 60.f * s, 300.f * s, 300.f * s);
		}
		Text(TEXT("<"), X + 40.f * s, Y + 170.f * s, 70.f, bActive ? FLinearColor::White : FLinearColor(0.4f, 0.4f, 0.45f), true, true);
		Text(TEXT(">"), X + PW - 40.f * s, Y + 170.f * s, 70.f, bActive ? FLinearColor::White : FLinearColor(0.4f, 0.4f, 0.45f), true, true);
		Text(TD.City.ToUpper(), X + PW * 0.5f, Y + 370.f * s, 30.f, FLinearColor(0.9f, 0.9f, 0.95f), true, false);
		Text(TD.Name.ToUpper(), X + PW * 0.5f, Y + 404.f * s, 58.f, TD.Primary.GetLuminance() > 0.08f ? TD.Primary : TD.Accent, true, true, 2.f);
		for (int32 p = 0; p < TD.Players.Num() && p < 2; ++p)
		{
			const FHCPlayerDef& D = TD.Players[p];
			const float PY = Y + 500.f * s + p * 140.f * s;
			Text(FString::Printf(TEXT("#%d  %s %s"), D.Number, *D.First.ToUpper(), *D.Last.ToUpper()), X + 40.f * s, PY, 28.f, FLinearColor::White, false, false);
			Text(FString::Printf(TEXT("\"%s\""), *D.Nick.ToUpper()), X + 40.f * s, PY + 36.f * s, 18.f, FLinearColor(1.f, 0.7f, 0.25f), false, false);
			const TCHAR* Labels[] = { TEXT("SPD"), TEXT("3PT"), TEXT("DNK"), TEXT("PWR"), TEXT("STL"), TEXT("BLK") };
			const int32 Vals[] = { D.Speed, D.Three, D.Dunk, D.Power, D.Steal, D.Block };
			for (int32 k = 0; k < 6; ++k)
			{
				const float BX = X + 40.f * s + k * 118.f * s;
				const float BY = PY + 70.f * s;
				Text(Labels[k], BX, BY, 15.f, FLinearColor(0.7f, 0.7f, 0.75f), false, false);
				Rect(BX, BY + 22.f * s, 100.f * s, 10.f * s, FLinearColor(0.15f, 0.15f, 0.18f));
				Rect(BX, BY + 22.f * s, 10.f * s * Vals[k], 10.f * s, FLinearColor(1.f, 0.35f + Vals[k] * 0.05f, 0.08f));
			}
		}
	}
	Text(TEXT("VS"), W * 0.5f, 420.f * s, 80.f, FLinearColor(1.f, 0.85f, 0.25f), true, true, 4.f);
	const FString Hint = bVersus ? TEXT("P1  A / D        P2  LEFT / RIGHT        ENTER  TIP OFF!")
		: TEXT("A / D  CHANGE TEAM        W / S  SWITCH SIDE        ENTER  TIP OFF!        ESC  BACK");
	Text(Hint, W * 0.5f, H - 70.f * s, 22.f, FLinearColor(0.85f, 0.85f, 0.9f), true, true);
}

void AHCHUD::DrawIntro()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	const float T = G->PhaseTime;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.f, 0.35f));
	for (int32 Side = 0; Side < 2; ++Side)
	{
		const int32 Team = Side == 0 ? 1 : 0;   // away team announced first, on the left
		const FHCTeamDef& TD = G->TeamDef(Team);
		const float Appear = FMath::Clamp((T - (Side == 0 ? 0.3f : 1.8f)) * 4.f, 0.f, 1.f);
		if (Appear <= 0.f)
		{
			continue;
		}
		const float Slide = (1.f - Appear) * 900.f * s * (Side == 0 ? -1.f : 1.f);
		const float CX = (Side == 0 ? W * 0.27f : W * 0.73f) + Slide;
		if (UTexture2D* L = TeamLogo(G->TeamIdx[Team]))
		{
			Tex(L, CX - 200.f * s, 220.f * s, 400.f * s, 400.f * s);
		}
		Text(TD.City.ToUpper(), CX, 640.f * s, 40.f, FLinearColor::White, true, true, 2.f);
		Text(TD.Name.ToUpper(), CX, 690.f * s, 80.f, TD.Primary.GetLuminance() > 0.08f ? TD.Primary : TD.Accent, true, true, 4.f);
	}
	if (T > 1.4f)
	{
		Text(TEXT("VS"), W * 0.5f, 380.f * s, 110.f, FLinearColor(1.f, 0.6f, 0.1f), true, true, 5.f);
	}
	Text(TEXT("TONIGHT AT THE HEAT CHECK ARENA"), W * 0.5f, 120.f * s, 34.f, FLinearColor(1.f, 0.85f, 0.3f), true, true, 2.f);
}

void AHCHUD::DrawBreak(bool bFinal)
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.02f, 0.72f));
	FString Title;
	if (bFinal)
	{
		Title = TEXT("FINAL");
	}
	else if (G->Quarter == 2)
	{
		Title = TEXT("HALFTIME");
	}
	else if (G->Quarter >= 4)
	{
		Title = TEXT("OVERTIME!");
	}
	else
	{
		Title = FString::Printf(TEXT("END OF QUARTER %d"), G->Quarter);
	}
	Text(Title, W * 0.5f, 50.f * s, 72.f, FLinearColor(1.f, 0.55f, 0.1f), true, true, 4.f);
	if (bFinal && !G->WinnerText.IsEmpty())
	{
		Text(G->WinnerText, W * 0.5f, 140.f * s, 44.f, FLinearColor(1.f, 0.9f, 0.4f), true, true, 3.f);
	}
	// line score
	const float TX = W * 0.5f - 520.f * s;
	float Y = 220.f * s;
	const int32 NQ = FMath::Max(4, G->Quarter);
	Text(TEXT("TEAM"), TX, Y, 22.f, FLinearColor(0.7f, 0.7f, 0.75f), false, false);
	for (int32 q = 0; q < NQ; ++q)
	{
		Text(q < 4 ? FString::Printf(TEXT("Q%d"), q + 1) : FString::Printf(TEXT("OT%d"), q - 3), TX + (420.f + q * 90.f) * s, Y, 22.f, FLinearColor(0.7f, 0.7f, 0.75f), true, false);
	}
	Text(TEXT("TOTAL"), TX + (420.f + NQ * 90.f + 40.f) * s, Y, 22.f, FLinearColor(1.f, 0.8f, 0.3f), true, false);
	for (int32 t = 0; t < 2; ++t)
	{
		Y = (262.f + t * 54.f) * s;
		const FHCTeamDef& TD = G->TeamDef(t);
		Rect(TX - 16.f * s, Y - 4.f * s, 8.f * s, 44.f * s, TD.Primary);
		Text(FString::Printf(TEXT("%s %s"), *TD.City.ToUpper(), *TD.Name.ToUpper()), TX, Y, 30.f, FLinearColor::White, false, false);
		for (int32 q = 0; q < NQ; ++q)
		{
			const FString V = q < G->Quarter ? FString::FromInt(G->QuarterScores[t][FMath::Min(q, 7)]) : TEXT("-");
			Text(V, TX + (420.f + q * 90.f) * s, Y, 30.f, FLinearColor(0.9f, 0.9f, 0.95f), true, false);
		}
		Text(FString::FromInt(G->Score[t]), TX + (420.f + NQ * 90.f + 40.f) * s, Y, 34.f, FLinearColor(1.f, 0.85f, 0.3f), true, false);
	}
	// player stats
	Y = 410.f * s;
	const TCHAR* Cols[] = { TEXT("PTS"), TEXT("FG"), TEXT("3PT"), TEXT("DNK"), TEXT("REB"), TEXT("AST"), TEXT("STL"), TEXT("BLK"), TEXT("SHV") };
	for (int32 k = 0; k < 9; ++k)
	{
		Text(Cols[k], TX + (470.f + k * 85.f) * s, Y, 20.f, FLinearColor(0.7f, 0.7f, 0.75f), true, false);
	}
	for (int32 i = 0; i < G->Players.Num(); ++i)
	{
		const AHCCharacter* C = G->Players[i];
		const float RY = Y + (42.f + i * 48.f) * s;
		Rect(TX - 16.f * s, RY - 2.f * s, 8.f * s, 36.f * s, G->TeamDef(C->Team).Primary);
		Text(FString::Printf(TEXT("#%d %s %s%s"), C->Def.Number, *C->Def.First.ToUpper(), *C->Def.Last.ToUpper(), C->bOnFire ? TEXT("  *FIRE*") : TEXT("")),
			TX, RY, 24.f, FLinearColor::White, false, false);
		const FHCStats& St = C->Stats;
		const FString Vals[] = { FString::FromInt(St.Points), FString::Printf(TEXT("%d-%d"), St.FGM, St.FGA), FString::Printf(TEXT("%d-%d"), St.TPM, St.TPA),
			FString::FromInt(St.Dunks), FString::FromInt(St.Rebounds), FString::FromInt(St.Assists), FString::FromInt(St.Steals), FString::FromInt(St.Blocks), FString::FromInt(St.Shoves) };
		for (int32 k = 0; k < 9; ++k)
		{
			Text(Vals[k], TX + (470.f + k * 85.f) * s, RY, 24.f, k == 0 ? FLinearColor(1.f, 0.85f, 0.3f) : FLinearColor(0.9f, 0.9f, 0.95f), true, false);
		}
	}
	const float Blink = 0.6f + 0.4f * FMath::Sin(Time * 5.f);
	Text(bFinal ? TEXT("PRESS ENTER FOR THE TITLE SCREEN") : TEXT("PRESS ENTER TO CONTINUE"), W * 0.5f, H - 110.f * s, 34.f, FLinearColor(1.f, 0.85f, 0.3f, Blink), true, true, 2.f);
}

void AHCHUD::DrawPause()
{
	AHCGameMode* G = GM();
	const float s = S();
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	Rect(0, 0, W, H, FLinearColor(0.f, 0.f, 0.f, 0.6f));
	Text(TEXT("PAUSED"), W * 0.5f, 220.f * s, 90.f, FLinearColor(1.f, 0.55f, 0.1f), true, true, 4.f);
	for (int32 i = 0; i < G->PauseItemCount(); ++i)
	{
		const bool bSel = i == G->PauseIndex;
		const float Y = (390.f + i * 80.f) * s;
		if (bSel)
		{
			Rect(W * 0.5f - 300.f * s, Y - 6.f * s, 600.f * s, 64.f * s, FLinearColor(1.f, 0.38f, 0.05f, 0.9f));
		}
		Text(G->PauseItemText(i), W * 0.5f, Y, 40.f, FLinearColor::White, true, bSel);
	}
	DrawControlsHint(H - 160.f * s);
}

void AHCHUD::UpdateFrameSample()
{
	if (LastHUDFrame == GFrameCounter) { return; }
	LastHUDFrame = GFrameCounter;
	const double Now = FPlatformTime::Seconds();
	if (SampleStart == 0.0)
	{
		SampleStart = Now;
		SampleFrames = 0;
		FrameMs = 0.f;
		FrameReading = TEXT("Measuring...");
		QualityReading = FHCOptions::PresetName();
		QualityLevel = FHCOptions::QualityTier();
		return;
	}
	++SampleFrames;
	const double Elapsed = Now - SampleStart;
	if (Elapsed >= 0.5)
	{
		FrameMs = 1000.0 * Elapsed / SampleFrames;
		FrameReading = FString::Printf(TEXT("%.0f FPS   /   %.2f ms"), 1000.f / FrameMs, FrameMs);
		QualityReading = FHCOptions::PresetName();
		QualityLevel = FHCOptions::QualityTier();
		SampleStart = Now;
		SampleFrames = 0;
	}
}

void AHCHUD::DrawQualityMeter(float X, float Y, float Width, bool bExpanded)
{
	const float s = S();
	const FLinearColor Ink(0.014f, 0.019f, 0.025f, 0.95f);
	const FLinearColor Muted(0.62f, 0.69f, 0.73f);
	const FLinearColor Gold(1.f, 0.59f, 0.08f);
	const float Padding = (bExpanded ? 24.f : 12.f) * s;
	const float Track = Width - 2.f * Padding;
	const float Left = X + Padding;
	Rect(X, Y, Width, (bExpanded ? 226.f : 61.f) * s, Ink);
	if (bExpanded)
	{
		Text(TEXT("IMAGE QUALITY"), Left, Y + 16.f*s, 16.f, Muted, false, false);
		Text(QualityReading, Left, Y + 38.f*s, 34.f, FLinearColor::White, false, false);
		const float Cell = (Track - 4.f * 6.f*s) / 5.f;
		for (int32 I = 0; I < 5; ++I)
		{
			Rect(Left + I * (Cell + 6.f*s), Y + 88.f*s, Cell, 6.f*s, I <= QualityLevel ? Gold : FLinearColor(0.13f, 0.16f, 0.18f));
		}
		Text(GM()->bPaused ? TEXT("FRAME TIME   /   PAUSED SCENE") : TEXT("FRAME TIME   /   LIVE COURT"),
			Left, Y + 116.f*s, 15.f, Muted, false, false);
	}
	Text(FrameReading, Left, Y + (bExpanded ? 140.f : 7.f)*s, bExpanded ? 29.f : 23.f, FLinearColor::White, false, false);
	const float BarY = Y + (bExpanded ? 183.f : 42.f)*s;
	constexpr float Budget = 1000.f / 120.f;
	Rect(Left, BarY, Track, 5.f*s, FLinearColor(0.13f, 0.16f, 0.18f));
	if (FrameMs > 0.f)
	{
		const FLinearColor Fill = FrameMs <= Budget ? FLinearColor(0.20f, 0.85f, 0.47f)
			: FrameMs <= 2.f * Budget ? Gold : FLinearColor(1.f, 0.24f, 0.18f);
		Rect(Left, BarY, Track * FMath::Min(FrameMs / (2.f*Budget), 1.f), 5.f*s, Fill);
	}
	Rect(Left + Track*0.5f - s, BarY - 3.f*s, 2.f*s, 11.f*s, FLinearColor::White);
	if (bExpanded) { Text(TEXT("120 FPS target   /   8.33 ms"), Left, BarY + 14.f*s, 17.f, Muted, false, false); }
}

void AHCHUD::DrawOptions()
{
	const auto& Options = GM()->Options;
	const bool bSound = Options.Page == EHCOptionsPage::Sound;
	const float W = Canvas->ClipX, H = Canvas->ClipY;
	UIScale = FMath::Min(H / 1080.f, W / 1120.f);
	const float s = S(), X = 38.f*s, Y = (H - 992.f*s)*0.5f;
	const float PW = 646.f*s, Left = X + 26.f*s, Right = X + PW - 26.f*s;
	const FLinearColor Panel(0.012f, 0.018f, 0.025f, 0.97f), Line(0.12f, 0.15f, 0.17f);
	const FLinearColor Muted(0.68f, 0.73f, 0.76f), Accent(1.f, 0.60f, 0.08f);
	Rect(X, Y, PW, 992.f*s, Panel);
	Rect(X, Y, PW, 4.f*s, Accent);
	Text(TEXT("OPTIONS"), Left, Y + 18.f*s, 48.f, FLinearColor::White, false, false);
	const float TabY = Y + 91.f*s, TabW = (Right - Left) * 0.5f;
	for (int32 I = 0; I < 2; ++I)
	{
		const bool bActive = I == (bSound ? 1 : 0);
		const float TX = Left + I*TabW;
		Text(I ? TEXT("SOUND") : TEXT("GRAPHICS"), TX + TabW*0.5f, TabY, 22.f, bActive ? Accent : Muted, true, false);
		Rect(TX, TabY + 37.f*s, TabW, (bActive ? 3.f : 1.f)*s, bActive ? Accent : Line);
	}
	const float RowH = (bSound ? 77.f : 47.f)*s;
	for (int32 I = 0; I < Options.NumRows(); ++I)
	{
		const float Top = Y + 146.f*s + I*RowH;
		const bool bSelected = I == Options.Row;
		if (bSelected)
		{
			Rect(Left - 10.f*s, Top, Right - Left + 20.f*s, RowH - s, FLinearColor(0.18f, 0.115f, 0.046f));
			Rect(Left - 10.f*s, Top, 4.f*s, RowH - s, Accent);
		}
		const float TY = Top + (RowH - 29.f*s)*0.5f;
		Text(Options.Label(I), Left + 7.f*s, TY, 23.f, bSelected ? FLinearColor::White : Muted, false, false);
		const FString Value = Options.Value(I);
		if (!Value.IsEmpty())
		{
			Text(Value, Right - 74.f*s, TY, 22.f, bSelected ? Accent : FLinearColor::White, true, false);
			if (bSelected)
			{
				Text(TEXT("<"), Right - 151.f*s, TY, 20.f, Accent, false, false);
				Text(TEXT(">"), Right - 8.f*s, TY, 20.f, Accent, false, false);
			}
		}
		const int32 Volume = Options.VolumePercent(I);
		if (Volume >= 0)
		{
			const float BarX = Left + 252.f*s, BarW = 145.f*s;
			Rect(BarX, Top + RowH*0.50f, BarW, 5.f*s, Line);
			Rect(BarX, Top + RowH*0.50f, BarW * Volume / 100.f, 5.f*s, bSelected ? Accent : Muted);
		}
	}
	Rect(Left, Y + 825.f*s, Right - Left, s, Line);
	const FString Help = Options.Help();
	// All descriptions fit two lines at the native Canvas font size.
	int32 Split = 58;
	if (Help.Len() > Split)
	{
		while (Split > 0 && Help[Split] != ' ') { --Split; }
		Text(Help.Left(Split), Left, Y + 846.f*s, 20.f, Muted, false, false, 0.f, false);
		Text(Help.Mid(Split + 1), Left, Y + 873.f*s, 20.f, Muted, false, false, 0.f, false);
	}
	else { Text(Help, Left, Y + 846.f*s, 20.f, Muted, false, false, 0.f, false); }
	Text(Options.IsReset() ? TEXT("ENTER / A   RESTORE DEFAULTS") :
		bSound && Options.VolumePercent(Options.Row) >= 0 ? TEXT("LEFT / RIGHT   ADJUST      ENTER / A   PREVIEW") : TEXT("LEFT / RIGHT   ADJUST"),
		Left, Y + 914.f*s, 18.f, Accent, false, false);
	Text(TEXT("UP / DOWN   SELECT      TAB / LB / RB   SWITCH      ESC / B   BACK"), Left, Y + 953.f*s,
		16.f, Muted, false, false);
	const float CardW = 348.f*s;
	DrawQualityMeter(W - X - CardW, Y, CardW, true);
}
