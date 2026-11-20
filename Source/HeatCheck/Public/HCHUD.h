#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "HCHUD.generated.h"

class UFont;
class UTexture2D;
class AHCGameMode;
class AHCCharacter;

/** All 2D UI drawn with Canvas: scoreboard, turbo/fire meters, call-outs, menus and stat screens. */
UCLASS()
class HEATCHECK_API AHCHUD : public AHUD
{
	GENERATED_BODY()
public:
	AHCHUD();
	virtual void BeginPlay() override;
	virtual void DrawHUD() override;

private:
	AHCGameMode* GM() const;
	float S() const { return UIScale; }
	void Text(const FString& Str, float X, float Y, float Size, const FLinearColor& Color, bool bCenter = false,
		bool bShadow = true, float Outline = 0.f, bool bBold = true, float DrawScale = 1.f);
	FVector2D Measure(const FString& Str, float Size, bool bBold = true) const;
	void Rect(float X, float Y, float W, float H, const FLinearColor& Color);
	void Tex(UTexture2D* T, float X, float Y, float W, float H, const FLinearColor& Tint = FLinearColor::White);
	void DrawScoreboard();
	void DrawPlayerCards();
	void DrawPlayerMarkers();
	void DrawPopups();
	void DrawShotMeter();
	void DrawTitle();
	void DrawMenu();
	void DrawTeamSelect();
	void DrawIntro();
	void DrawBreak(bool bFinal);
	void DrawPause();
	void DrawOptions();
	void DrawQualityMeter(float X, float Y, float Width, bool bExpanded);
	void UpdateFrameSample();
	double SampleStart = 0.0;
	uint64 LastHUDFrame = 0;
	int32 SampleFrames = 0;
	float FrameMs = 0.f;
	FString FrameReading;
	FString QualityReading;
	int32 QualityLevel = 0;
	void DrawControlsHint(float Y);
	FString ClockString(float Seconds) const;
	UTexture2D* TeamLogo(int32 RosterIndex);

	UPROPERTY(Transient)
	TObjectPtr<UFont> FontBold;
	UPROPERTY(Transient)
	TObjectPtr<UFont> FontRegular;
	UPROPERTY(Transient)
	TObjectPtr<UTexture2D> Logo;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UTexture2D>> TeamLogos;
	float UIScale = 1.f;
	float Time = 0.f;
};
