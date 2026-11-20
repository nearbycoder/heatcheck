#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "HCTypes.h"
#include "HCPlayerController.generated.h"

/**
 * Reads the keyboard / gamepad directly every frame and routes it to the match:
 *   P1: WASD move, J shoot/jump, K pass/steal, H shove, L or Left Shift turbo (Space also shoots)
 *       gamepad: left stick, A shoot, X pass, Y shove, RB/RT turbo
 *   P2: arrow keys move, Numpad1 or ',' shoot, Numpad2 or '.' pass, Numpad0 or M shove, Numpad3 or '/' or Right Shift turbo
 *   Enter/Start confirm, Esc/P pause.
 */
UCLASS()
class HEATCHECK_API AHCPlayerController : public APlayerController
{
	GENERATED_BODY()
public:
	AHCPlayerController();
	virtual void BeginPlay() override;
	virtual void PlayerTick(float DeltaTime) override;

private:
	void ReadPlayer(int32 P, FHCInput& Out, bool bAllowGamepad);
	bool Pressed(const FKey& K) const;
	bool Down(const FKey& K) const;
	bool Released(const FKey& K) const;
	float RepeatTimer[4] = { 0, 0, 0, 0 };

	// -hcautopilot: drives P1 through the real human input path (menus, shots, dunks, steals) for testing
	void Autopilot(class AHCGameMode* G, float Dt);
	bool bAutopilot = false;
	float AutoT = 0.f;
	float AutoShootHold = -1.f;
	float AutoHoldBall = 0.f;
	float AutoActCooldown = 0.f;
};
