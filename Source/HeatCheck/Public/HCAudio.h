#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "HCOptions.h"
#include "HCAudio.generated.h"

class USoundClass;
class USoundMix;
class USoundBase;
class UAudioComponent;

/** Loads the generated sound effects / announcer lines / music by name and plays them in 2D. */
UCLASS()
class HEATCHECK_API UHCAudio : public UObject
{
	GENERATED_BODY()
public:
	void Init(UWorld* InWorld, const FHCSoundLevels& Levels);
	void ApplyMix(const FHCSoundLevels& Levels);
	void Preview(EHCMixBus Bus);
	void StopPreview();
	void Shutdown();
	void Tick(float Dt);

	void Sfx(const FString& Name, float Volume = 1.f, float Pitch = 1.f);
	/** Plays Base_01..Base_N at random (falls back to Base). */
	void SfxVariant(const FString& Base, int32 Count, float Volume = 1.f, float PitchJitter = 0.06f);
	/** Announcer line; lower priority lines are dropped while a line is playing. */
	void Voice(const FString& Name, int32 Priority = 1);
	void VoiceVariant(const FString& Base, int32 Count, int32 Priority = 1);
	void PlayMusic(const FString& Name, float Volume = 0.6f);
	void StopMusic(float FadeOut = 1.f);
	void SetCrowd(float Energy);

private:
	USoundBase* Get(const FString& Name);
	TWeakObjectPtr<UWorld> World;
	UPROPERTY(Transient) TObjectPtr<USoundMix> OptionsMix;
	UPROPERTY(Transient) TArray<TObjectPtr<USoundClass>> MixClasses;
	UPROPERTY(Transient) TObjectPtr<UAudioComponent> PreviewComp;
	UPROPERTY(Transient)
	TMap<FString, TObjectPtr<USoundBase>> Cache;
	TSet<FString> Missing;
	UPROPERTY(Transient)
	TObjectPtr<UAudioComponent> MusicComp;
	UPROPERTY(Transient)
	TObjectPtr<UAudioComponent> CrowdComp;
	UPROPERTY(Transient)
	TObjectPtr<UAudioComponent> VoiceComp;
	FString CurrentMusic;
	int32 VoicePriority = 0;
	float CrowdEnergy = 0.f;
	float CrowdVolume = 0.f;
};
