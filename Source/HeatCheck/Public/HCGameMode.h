#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "HCTypes.h"
#include "HCOptions.h"
#include "HCGameMode.generated.h"

class AHCBall;
class AHCReferee;
class AHCHoop;
class AHCArena;
class AHCCharacter;
class AHCCameraDirector;
class UHCAudio;

/** Which UI screen is up. Menus run on top of a CPU-vs-CPU attract-mode game. */
enum class EHCScreen : uint8 { Title, Menu, TeamSelect, Game };

/** Match flow. */
enum class EHCPhase : uint8
{
	Intro,       // matchup presentation
	TipOff,
	Live,
	Scored,      // ball dropping through the net, players resetting
	Inbound,     // waiting for the inbound pass
	Violation,   // shot clock violation pause
	QuarterEnd,
	Break,       // quarter / half-time stats screen
	GameOver
};

enum class EHCMode : uint8 { OnePlayer, TwoPlayerCoop, TwoPlayerVersus, Watch };

struct FHCPopup
{
	FString Text;
	FString Sub;
	FLinearColor Color = FLinearColor::White;
	float Time = 0.f;
	float Duration = 1.8f;
	float Scale = 1.f;
	bool bBig = true;
};

/** Per-CPU-player brain memory. */
struct FHCAIState
{
	float Think = 0.f;
	FVector2D Spot = FVector2D::ZeroVector;
	float SpotTimer = 0.f;
	float ShootHold = -1.f;       // >=0 while holding a jump shot; release when reached
	float JumpAt = -1.f;          // delayed block / rebound jump
	float HoldTimer = 0.f;        // time spent holding the ball
	float PassAt = -1.f;          // delayed (requested) pass
	bool bWantTurbo = false;
	float Aggro = 0.f;            // random per-possession aggression
	int32 Intent = -1;            // 0 drive, 1 pull-up jumper, 2 spot-up three (chosen when the ball is caught)
	FVector2D IntentSpot = FVector2D::ZeroVector;
};

UCLASS()
class HEATCHECK_API AHCGameMode : public AGameModeBase
{
	GENERATED_BODY()
public:
	AHCGameMode();
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void Tick(float DeltaSeconds) override;

	// ---------------------------------------------------------------- objects
	UPROPERTY(Transient)
	TObjectPtr<AHCBall> Ball;
	UPROPERTY(Transient)
	TObjectPtr<AHCReferee> Referee;
	UPROPERTY(Transient)
	TObjectPtr<AHCHoop> Hoops[2];
	UPROPERTY(Transient)
	TArray<TObjectPtr<AHCCharacter>> Players;
	UPROPERTY(Transient)
	TObjectPtr<AHCArena> Arena;
	UPROPERTY(Transient)
	TObjectPtr<AHCCameraDirector> CameraDirector;
	UPROPERTY(Transient)
	TObjectPtr<UHCAudio> Audio;

	// ---------------------------------------------------------------- settings
	FHCOptions Options;
	EHCMode Mode = EHCMode::OnePlayer;
	EHCDifficulty Difficulty = EHCDifficulty::Normal;
	int32 QuarterMinutes = 3;
	bool bBigHeads = false;
	int32 TeamIdx[2] = { 0, 1 };

	// ---------------------------------------------------------------- match state
	EHCScreen Screen = EHCScreen::Title;
	EHCPhase Phase = EHCPhase::Intro;
	float PhaseTime = 0.f;
	bool bPaused = false;
	int32 PauseIndex = 0;
	bool bAttract = true;
	int32 Score[2] = { 0, 0 };
	int32 QuarterScores[2][8];
	int32 Quarter = 1;
	float GameClock = 180.f;
	float ShotClock = HC::ShotClockLength;
	int32 ShotClockTeam = -1;
	int32 PossessionTeam = -1;
	int32 InboundTeam = 0;
	int32 InboundHoop = 0;           // basket under which the inbound happens (the one just scored on)
	int32 FirstPossessionTeam = 0;   // tip-off winner (alternating possession for quarter starts)
	bool bBuzzerPending = false;     // quarter clock hit zero while a shot was in flight
	bool bTipTouched = false;
	float CrowdHype = 0.f;
	int32 MenuIndex = 0;
	int32 SelectSide = 0;
	TArray<FHCPopup> Popups;
	FHCAIState AI[4];
	FString LastEventText;
	float LastPassTime = -10.f;
	TWeakObjectPtr<AHCCharacter> LastPasser;
	TWeakObjectPtr<AHCCharacter> TipJumpers[2];
	float BreakTimer = 0.f;
	float CountdownBeep = 0.f;
	FString WinnerText;

	/** Input from the local humans (P1, P2), written by the player controller. */
	FHCInput HumanInput[2];

	// ---------------------------------------------------------------- queries
	const FHCTeamDef& TeamDef(int32 Team) const;
	AHCCharacter* Teammate(const AHCCharacter* C) const;
	void GetOpponents(const AHCCharacter* C, TArray<AHCCharacter*>& Out) const;
	AHCCharacter* NearestOpponent(const AHCCharacter* C, float* OutDist = nullptr) const;
	int32 AttackHoop(int32 Team) const;
	FVector RimCenter(int32 Hoop) const;
	FVector HoopFloor(int32 Hoop) const;
	float DistToHoop(const FVector& Pos, int32 Hoop) const;
	bool IsThree(const FVector& Pos, int32 Hoop) const;
	bool IsPlayLive() const { return Phase == EHCPhase::Live || Phase == EHCPhase::TipOff || Phase == EHCPhase::Inbound; }
	bool InMenus() const { return Screen != EHCScreen::Game; }
	int32 HumanCount() const;
	bool IsHumanTeam(int32 Team) const;
	float ClockSeconds() const { return GameClock; }

	// ---------------------------------------------------------------- events (characters)
	void ReleaseShot(AHCCharacter* Shooter, float Quality, bool bLayup);
	void DunkSlam(AHCCharacter* Dunker);
	void DunkTakeoff(AHCCharacter* Dunker);
	void ReleasePass(AHCCharacter* From, AHCCharacter* To, bool bAlley);
	void ResolveShove(AHCCharacter* Shover, AHCCharacter* Target);
	void ResolveSteal(AHCCharacter* Stealer);
	void RequestPass(AHCCharacter* Holder, AHCCharacter* To);
	void RequestShot(AHCCharacter* Holder);
	void OnJump(AHCCharacter* C);

	// ---------------------------------------------------------------- events (ball)
	void OnBallScored(int32 Hoop, AHCCharacter* Shooter, int32 Points, bool bDunk);
	void OnBallRim(int32 Hoop, float Speed);
	void OnBallBoard(int32 Hoop, float Speed);
	void OnBallBounce(float Speed);
	void OnBallCaught(AHCCharacter* C, AHCCharacter* PassedBy);
	void OnPassIntercepted(AHCCharacter* By, AHCCharacter* From);

	// ---------------------------------------------------------------- UI / menu
	void Popup(const FString& Text, const FLinearColor& Color, float Scale = 1.f, const FString& Sub = FString(), float Duration = 1.8f);
	void MenuUp();
	void MenuDown();
	void MenuLeft(int32 Player);
	void MenuRight(int32 Player);
	void MenuConfirm(int32 Player);
	void MenuBack();
	void TogglePause();
	void QuitGame();
	FString MenuItemText(int32 Index) const;
	int32 MenuItemCount() const { return 9; }
	FString PauseItemText(int32 Index) const;
	int32 PauseItemCount() const { return 6; }

	// automation helpers
	bool bAutoShots = false;
	float AutoTimer = 0.f;
	int32 AutoShotIndex = 0;

private:
	void SpawnWorld();
	void ReturnToTitle();
	void TickShotDefense(float Dt);
	void AIShootNow(AHCCharacter* C, FHCAIState& S);
	void PlaceForQuarterStart(int32 InTeam, int32 Hoop);
	void SetupTeams(bool bForAttract);
	void StartMatch();
	void ResetMatchState();
	void SetPhase(EHCPhase P);
	void TickPhase(float Dt);
	void TickClocks(float Dt);
	void TickLooseBall(float Dt);
	void TickTipOff(float Dt);
	void TickPopups(float Dt);
	void TickAutomation(float Dt);
	void AssignControl();
	void PositionForTipOff();
	void BeginInbound(int32 Team, int32 Hoop);
	void PlaceInbound();
	void EndQuarter();
	void StartQuarter();
	void GiveBall(AHCCharacter* C);
	void ChangePossession(int32 Team);
	void UpdateHeat(AHCCharacter* Scorer, int32 Points, bool bDunk, bool bThree, bool bGoaltend);
	float ShotChance(const AHCCharacter* Shooter, float Quality, bool bLayup, bool bThree, float Dist) const;
	float CpuBias(int32 Team) const;
	void AnnounceScore(AHCCharacter* Scorer, int32 Points, bool bDunk);

	// AI (HCAI.cpp)
	void TickAI(AHCCharacter* C, FHCAIState& S, float Dt);
	void AIOffenseWithBall(AHCCharacter* C, FHCAIState& S, float Dt);
	void AIOffenseOffBall(AHCCharacter* C, FHCAIState& S, float Dt);
	void AIDefense(AHCCharacter* C, FHCAIState& S, float Dt);
	void AIChaseBall(AHCCharacter* C, FHCAIState& S, float Dt);
	void AIMoveTo(AHCCharacter* C, const FVector2D& Target, float Dt, float Slow = 60.f);
	float AIReaction() const;
	bool LaneOpen(const AHCCharacter* C, const FVector& To, float Width) const;
	float OpenSpace(const FVector2D& P, int32 DefTeam) const;

	float Time = 0.f;
};
