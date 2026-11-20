#include "HCAudio.h"
#include "HeatCheck.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundWave.h"
#include "Sound/SoundClass.h"
#include "Sound/SoundMix.h"
#include "Components/AudioComponent.h"
#include "Kismet/GameplayStatics.h"

void UHCAudio::Init(UWorld* InWorld, const FHCSoundLevels& Levels)
{
	World = InWorld;
	OptionsMix = LoadObject<USoundMix>(nullptr, TEXT("/Game/HeatCheck/Audio/Mix/Mix_Options"));
	const TCHAR* Names[] = { TEXT("Music"), TEXT("Announcer"), TEXT("Crowd"), TEXT("Effects"), TEXT("Interface") };
	static_assert(UE_ARRAY_COUNT(Names) + 1 == (int32)EHCMixBus::Count);
	for (const TCHAR* Name : Names)
	{
		const FString Path = FString::Printf(TEXT("/Game/HeatCheck/Audio/Mix/SC_%s"), Name);
		MixClasses.Add(LoadObject<USoundClass>(nullptr, *Path));
	}
	ApplyMix(Levels);
	UGameplayStatics::PushSoundMixModifier(InWorld, OptionsMix);
	// Load the small arena sound bank before tip-off. First-time commentary and
	// scoring cues otherwise synchronously flush their packages on the game thread.
	IAssetRegistry& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
	Registry.WaitForPremadeAssetRegistry();
	TArray<FAssetData> Sounds;
	Registry.GetAssetsByPath(TEXT("/Game/HeatCheck/Audio"), Sounds);
	for (const FAssetData& Asset : Sounds)
	{
		if (USoundBase* Sound = Cast<USoundBase>(Asset.GetAsset()))
		{
			Cache.Add(Asset.AssetName.ToString(), Sound);
		}
	}
}

void UHCAudio::ApplyMix(const FHCSoundLevels& Levels)
{
	for (int32 I = 0; I < MixClasses.Num(); ++I)
	{
		UGameplayStatics::SetSoundMixClassOverride(World.Get(), OptionsMix, MixClasses[I],
			Levels.Gain((EHCMixBus)(I + 1)), 1.f, Levels.bMuted ? 0.f : 0.04f, false);
	}
}

void UHCAudio::StopPreview()
{
	if (IsValid(PreviewComp)) { PreviewComp->Stop(); }
	PreviewComp = nullptr;
}

void UHCAudio::Preview(EHCMixBus Bus)
{
	StopPreview();
	const TCHAR* Samples[] = {TEXT("S_UI_Select"), TEXT("M_Title"), TEXT("VO_TipOff"), TEXT("S_CrowdCheer_01"), TEXT("S_Bounce_01"), TEXT("S_UI_Move")};
	static_assert(UE_ARRAY_COUNT(Samples) == (int32)EHCMixBus::Count);
	if (Bus == EHCMixBus::Music && IsValid(MusicComp) && MusicComp->IsPlaying()) { return; }
	PreviewComp = UGameplayStatics::SpawnSound2D(World.Get(), Get(Samples[(int32)Bus]));
	if (PreviewComp && Bus == EHCMixBus::Music) { PreviewComp->FadeOut(2.5f, 0.f); }
}

void UHCAudio::Shutdown()
{
	StopPreview();
	if (IsValid(MusicComp)) { MusicComp->Stop(); }
	if (IsValid(CrowdComp)) { CrowdComp->Stop(); }
	UGameplayStatics::PopSoundMixModifier(World.Get(), OptionsMix);
}

USoundBase* UHCAudio::Get(const FString& Name)
{
	if (TObjectPtr<USoundBase>* Found = Cache.Find(Name))
	{
		return *Found;
	}
	if (Missing.Contains(Name))
	{
		return nullptr;
	}
	const FString Path = FString::Printf(TEXT("/Game/HeatCheck/Audio/%s.%s"), *Name, *Name);
	USoundBase* S = LoadObject<USoundBase>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (S)
	{
		Cache.Add(Name, S);
	}
	else
	{
		Missing.Add(Name);
	}
	return S;
}

void UHCAudio::Sfx(const FString& Name, float Volume, float Pitch)
{
	if (USoundBase* S = Get(Name))
	{
		UGameplayStatics::PlaySound2D(World.Get(), S, Volume, Pitch);
	}
}

void UHCAudio::SfxVariant(const FString& Base, int32 Count, float Volume, float PitchJitter)
{
	const FString Name = FString::Printf(TEXT("%s_%02d"), *Base, FMath::RandRange(1, FMath::Max(1, Count)));
	const float Pitch = 1.f + FMath::FRandRange(-PitchJitter, PitchJitter);
	if (Get(Name))
	{
		Sfx(Name, Volume, Pitch);
	}
	else
	{
		Sfx(Base, Volume, Pitch);
	}
}

void UHCAudio::Voice(const FString& Name, int32 Priority)
{
	USoundBase* S = Get(Name);
	if (!S || !World.IsValid())
	{
		return;
	}
	if (VoiceComp && VoiceComp->IsPlaying())
	{
		if (Priority <= VoicePriority)
		{
			return;
		}
		VoiceComp->Stop();
	}
	VoiceComp = UGameplayStatics::SpawnSound2D(World.Get(), S, 1.f, 1.f, 0.f, nullptr, false, true);
	VoicePriority = Priority;
}

void UHCAudio::VoiceVariant(const FString& Base, int32 Count, int32 Priority)
{
	Voice(FString::Printf(TEXT("%s_%02d"), *Base, FMath::RandRange(1, FMath::Max(1, Count))), Priority);
}

void UHCAudio::PlayMusic(const FString& Name, float Volume)
{
	if (CurrentMusic == Name && MusicComp && MusicComp->IsPlaying())
	{
		MusicComp->SetVolumeMultiplier(Volume);
		return;
	}
	if (MusicComp)
	{
		MusicComp->FadeOut(0.8f, 0.f);
		MusicComp = nullptr;
	}
	if (USoundBase* S = Get(Name))
	{
		MusicComp = UGameplayStatics::SpawnSound2D(World.Get(), S, Volume, 1.f, 0.f, nullptr, true, false);
		if (MusicComp)
		{
			MusicComp->FadeIn(1.0f, Volume);
		}
		CurrentMusic = Name;
	}
}

void UHCAudio::StopMusic(float FadeOut)
{
	if (MusicComp)
	{
		MusicComp->FadeOut(FadeOut, 0.f);
		MusicComp = nullptr;
	}
	CurrentMusic.Reset();
}

void UHCAudio::SetCrowd(float Energy)
{
	CrowdEnergy = Energy;
}

void UHCAudio::Tick(float Dt)
{
	if (!CrowdComp && World.IsValid())
	{
		if (USoundBase* S = Get(TEXT("S_CrowdLoop")))
		{
			CrowdComp = UGameplayStatics::SpawnSound2D(World.Get(), S, 0.3f, 1.f, 0.f, nullptr, true, false);
		}
	}
	if (CrowdComp)
	{
		const float Target = 0.28f + 0.55f * FMath::Clamp(CrowdEnergy, 0.f, 1.f);
		CrowdVolume = FMath::FInterpTo(CrowdVolume, Target, Dt, 2.f);
		CrowdComp->SetVolumeMultiplier(CrowdVolume);
	}
}
