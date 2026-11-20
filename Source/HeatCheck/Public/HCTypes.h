#pragma once

#include "CoreMinimal.h"

/** Court geometry (Unreal units = cm). The court runs along X, center court at the origin. */
namespace HC
{
	constexpr float CourtHalfLength = 1432.5f;
	constexpr float CourtHalfWidth = 762.f;
	constexpr float RimX = 1272.5f;          // rim centre distance from center court
	constexpr float RimZ = 305.f;            // 10 ft
	constexpr float RimRadius = 22.86f;      // inner radius
	constexpr float RimTube = 1.0f;
	constexpr float BackboardX = 1310.5f;    // front face of the glass
	constexpr float BackboardHalfWidth = 91.5f;
	constexpr float BackboardBottom = 290.f;
	constexpr float BackboardTop = 397.f;
	constexpr float BallRadius = 12.f;
	constexpr float ThreeRadius = 724.f;
	constexpr float ThreeCornerY = 670.f;
	constexpr float Gravity = 980.f;
	constexpr float PlayerHalfHeight = 100.f;
	constexpr float PlayerRadius = 38.f;
	constexpr float BoundsMargin = 70.f;      // how far players may step past the lines
	constexpr float ShotClockLength = 24.f;
}

enum class EHCAnim : uint8
{
	Idle, Defense, DribbleIdle, Run, Sprint, RunDribble, HoldBall, JumpShot, Layup, Dunk, DunkWindmill,
	Pass, Shove, Steal, Block, Fall, GetUp, Celebrate, ShuffleLeft, ShuffleRight, Backpedal, Land, Tip, Count
};

/** Per-frame input for one player, filled by a human controller or the AI. */
struct FHCInput
{
	FVector2D Move = FVector2D::ZeroVector;   // x = court +X, y = court +Y (already in world space)
	bool bTurbo = false;
	bool bShootDown = false;
	bool bShootPressed = false;
	bool bShootReleased = false;
	bool bPassPressed = false;
	bool bShovePressed = false;

	void ClearEdges() { bShootPressed = bShootReleased = bPassPressed = bShovePressed = false; }
};

enum class EHCHair : uint8 { None, Buzz, Flattop, Afro, Braids, Mohawk, Curls, Bun };
enum class EHCBeard : uint8 { None, Full, Goatee };

struct FHCPlayerDef
{
	FString First;
	FString Last;
	FString Nick;
	int32 Number = 0;
	// ratings 1..10
	int32 Speed = 5, Shoot = 5, Three = 5, Dunk = 5, Pass = 5, Power = 5, Steal = 5, Block = 5, Clutch = 5;
	// look
	FLinearColor Skin = FLinearColor::White;
	EHCHair Hair = EHCHair::Buzz;
	FLinearColor HairColor = FLinearColor::Black;
	EHCBeard Beard = EHCBeard::None;
	bool bHeadband = false;
	bool bWristbands = false;
	float Height = 1.0f;   // uniform-ish scale
	float Build = 1.0f;    // width scale
};

struct FHCTeamDef
{
	FString City;
	FString Name;
	FString Abbr;
	FLinearColor Primary;
	FLinearColor Secondary;
	FLinearColor Accent;
	TArray<FHCPlayerDef> Players;
};

namespace HCRoster
{
	const TArray<FHCTeamDef>& Teams();
	FLinearColor Hex(const TCHAR* Hex); // sRGB hex -> linear
}

enum class EHCDifficulty : uint8 { Easy, Normal, Hard };
