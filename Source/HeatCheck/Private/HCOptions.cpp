#include "HCOptions.h"
#include "HCAudio.h"
#include "GameFramework/GameUserSettings.h"
#include "Misc/ConfigCacheIni.h"

namespace
{
using Settings = UGameUserSettings;
using Getter = int32 (Settings::*)() const;
using Setter = void (Settings::*)(int32);
struct FOptionRow
{
	const TCHAR* Label;
	const TCHAR* Help;
	Getter Get = nullptr;
	Setter Set = nullptr;
};

enum EGraphicsRow { Preset, Resolution, Shadow, Texture, AA, Reflection, Effects, Post, Shading, Distance, Cap, VSync, Meter, ResetGraphics };
constexpr FOptionRow GraphicsRows[] = {
	{TEXT("Quality preset"), TEXT("Change all image settings together.")},
	{TEXT("Render scale"), TEXT("Higher values sharpen the court and players. The HUD stays at native resolution.")},
	{TEXT("Shadows"), TEXT("Sharpen player shadows. Cinematic adds shadows from the overhead softbox."), &Settings::GetShadowQuality, &Settings::SetShadowQuality},
	{TEXT("Textures"), TEXT("Increase surface detail on the hardwood and uniforms."), &Settings::GetTextureQuality, &Settings::SetTextureQuality},
	{TEXT("Anti-aliasing"), TEXT("Smooth moving edges on court lines, players and fans."), &Settings::GetAntiAliasingQuality, &Settings::SetAntiAliasingQuality},
	{TEXT("Reflections"), TEXT("Adjust reflections on glossy surfaces."), &Settings::GetReflectionQuality, &Settings::SetReflectionQuality},
	{TEXT("Effects"), TEXT("Adjust the rendering quality of translucent effects."), &Settings::GetVisualEffectQuality, &Settings::SetVisualEffectQuality},
	{TEXT("Post-processing"), TEXT("Adjust bloom and ambient shading around the arena."), &Settings::GetPostProcessingQuality, &Settings::SetPostProcessingQuality},
	{TEXT("Shading"), TEXT("Adjust material lighting and the number of spotlights sweeping the stands."), &Settings::GetShadingQuality, &Settings::SetShadingQuality},
	{TEXT("Arena detail"), TEXT("Increase view distance and bring the upper-deck crowd into view and motion."), &Settings::GetViewDistanceQuality, &Settings::SetViewDistanceQuality},
	{TEXT("Frame rate limit"), TEXT("Set the maximum FPS. The meter always marks the 120 FPS target.")},
	{TEXT("VSync"), TEXT("Synchronize presentation with the display. Available refresh rates depend on the display.")},
	{TEXT("In-game meter"), TEXT("Show measured frame time and FPS during the match.")},
	{TEXT("Restore graphics defaults"), TEXT("Restore Balanced, a 120 FPS cap, VSync off and the in-game meter.")}
};
constexpr FOptionRow SoundRows[] = {
	{TEXT("Master"), TEXT("Adjust the entire arena mix.")},
	{TEXT("Music"), TEXT("Set the level of title and halftime music.")},
	{TEXT("Announcer"), TEXT("Set the level of play-by-play calls.")},
	{TEXT("Crowd"), TEXT("Set the level of crowd ambience, cheers and reactions.")},
	{TEXT("Gameplay effects"), TEXT("Set the level of dribbles, sneakers, whistles and rim impacts.")},
	{TEXT("Menu sounds"), TEXT("Set the level of menu navigation and selection cues.")},
	{TEXT("Mute all"), TEXT("Silence all channels and keep their individual levels.")},
	{TEXT("Restore sound defaults"), TEXT("Unmute the game and return every channel to 100%.")}
};
constexpr const TCHAR* VolumeKeys[] = {TEXT("Master"), TEXT("Music"), TEXT("Announcer"), TEXT("Crowd"), TEXT("Effects"), TEXT("Interface")};
constexpr const TCHAR* Presets[] = {TEXT("Performance"), TEXT("Balanced"), TEXT("High"), TEXT("Ultra"), TEXT("Cinematic")};
constexpr const TCHAR* Detail[] = {TEXT("Low"), TEXT("Medium"), TEXT("High"), TEXT("Epic"), TEXT("Cinematic")};
constexpr int32 Caps[] = {30, 60, 90, 120, 144, 165, 240, 0};
constexpr int32 BusCount = (int32)EHCMixBus::Count;
constexpr const TCHAR* Section = TEXT("HeatCheck.Options");
static_assert(UE_ARRAY_COUNT(GraphicsRows) == ResetGraphics + 1 && UE_ARRAY_COUNT(VolumeKeys) == BusCount && UE_ARRAY_COUNT(SoundRows) == BusCount + 2);

float RenderScale(const Settings& S)
{
	float Normalized, Value, Min, Max;
	S.GetResolutionScaleInformationEx(Normalized, Value, Min, Max);
	return Value;
}

const TCHAR* OnOff(bool Value) { return Value ? TEXT("On") : TEXT("Off"); }
}

float FHCSoundLevels::Gain(EHCMixBus Bus) const
{
	const float Master = bMuted ? 0.f : Volume[0] * 0.01f;
	return Bus == EHCMixBus::Master ? Master : Master * (Volume[(int32)Bus] * 0.01f);
}

void FHCOptions::Load()
{
	for (int32 I = 0; I < BusCount; ++I)
	{
		GConfig->GetInt(Section, VolumeKeys[I], Sound.Volume[I], GGameUserSettingsIni);
		Sound.Volume[I] = FMath::Clamp(Sound.Volume[I], 0, 100);
	}
	GConfig->GetBool(Section, TEXT("Mute"), Sound.bMuted, GGameUserSettingsIni);
	GConfig->GetBool(Section, TEXT("ShowMeter"), bShowMeter, GGameUserSettingsIni);
}

void FHCOptions::Save()
{
	if (!bDirty) { return; }
	for (int32 I = 0; I < BusCount; ++I)
	{
		GConfig->SetInt(Section, VolumeKeys[I], Sound.Volume[I], GGameUserSettingsIni);
	}
	GConfig->SetBool(Section, TEXT("Mute"), Sound.bMuted, GGameUserSettingsIni);
	GConfig->SetBool(Section, TEXT("ShowMeter"), bShowMeter, GGameUserSettingsIni);
	Settings::GetGameUserSettings()->SaveSettings();
	bDirty = false;
}

void FHCOptions::Open(EHCOptionsPage NewPage)
{
	Page = NewPage;
	Row = 0;
}

void FHCOptions::Close(UHCAudio& Audio)
{
	Audio.StopPreview();
	Save();
	Page = EHCOptionsPage::Closed;
}

int32 FHCOptions::NumRows() const
{
	return Page == EHCOptionsPage::Sound ? UE_ARRAY_COUNT(SoundRows) : UE_ARRAY_COUNT(GraphicsRows);
}

void FHCOptions::Move(int32 Direction)
{
	Row = (Row + Direction + NumRows()) % NumRows();
}

const TCHAR* FHCOptions::Label(int32 Index) const
{
	return (Page == EHCOptionsPage::Sound ? SoundRows : GraphicsRows)[Index].Label;
}

const TCHAR* FHCOptions::Help() const
{
	return (Page == EHCOptionsPage::Sound ? SoundRows : GraphicsRows)[Row].Help;
}

int32 FHCOptions::VolumePercent(int32 Index) const
{
	return Page == EHCOptionsPage::Sound && Index < BusCount ? Sound.Volume[Index] : -1;
}

const TCHAR* FHCOptions::PresetName()
{
	const int32 Level = Settings::GetGameUserSettings()->GetOverallScalabilityLevel();
	return Level >= 0 && Level < UE_ARRAY_COUNT(Presets) ? Presets[Level] : TEXT("Custom");
}

int32 FHCOptions::QualityTier()
{
	const Settings& S = *Settings::GetGameUserSettings();
	const int32 Count = Distance - Shadow + 1;
	int32 Sum = 0;
	for (int32 I = Shadow; I <= Distance; ++I) { Sum += (S.*GraphicsRows[I].Get)(); }
	return FMath::Clamp(FMath::RoundToInt(float(Sum) / Count), 0, 4);
}

FString FHCOptions::Value(int32 Index) const
{
	const int32 Percent = VolumePercent(Index);
	if (Percent >= 0) { return FString::Printf(TEXT("%d%%"), Percent); }
	if (Index == NumRows() - 1) { return TEXT(""); }
	if (Page == EHCOptionsPage::Sound) { return OnOff(Sound.bMuted); }
	const Settings& S = *Settings::GetGameUserSettings();
	if (GraphicsRows[Index].Get)
	{
		return Detail[FMath::Clamp((S.*GraphicsRows[Index].Get)(), 0, 4)];
	}
	switch (Index)
	{
	case Preset: return PresetName();
	case Resolution:
		return RenderScale(S) <= 0.f ? TEXT("Auto") : FString::Printf(TEXT("%.0f%%"), RenderScale(S));
	case Cap: return S.GetFrameRateLimit() > 0.f ? FString::Printf(TEXT("%.0f FPS"), S.GetFrameRateLimit()) : TEXT("Unlimited");
	case VSync: return OnOff(S.IsVSyncEnabled());
	default: return OnOff(bShowMeter);
	}
}

void FHCOptions::Adjust(int32 Direction, UHCAudio& Audio)
{
	if (IsReset()) { return; }
	bDirty = true;
	if (Page == EHCOptionsPage::Sound)
	{
		if (Row == BusCount) { Sound.bMuted = !Sound.bMuted; }
		else { Sound.Volume[Row] = FMath::Clamp(Sound.Volume[Row] + Direction * 5, 0, 100); }
		Audio.ApplyMix(Sound);
		return;
	}
	Settings& S = *Settings::GetGameUserSettings();
	if (GraphicsRows[Row].Get)
	{
		const int32 Level = (S.*GraphicsRows[Row].Get)();
		(S.*GraphicsRows[Row].Set)(FMath::Clamp(Level + Direction, 0, 4));
	}
	else
	{
		switch (Row)
		{
		case Preset:
			S.SetOverallScalabilityLevel(FMath::Clamp(QualityTier() + Direction, 0, 4));
			break;
		case Resolution:
		{
			const float Current = RenderScale(S);
			S.SetResolutionScaleValueEx(FMath::Clamp((Current > 0.f ? Current : 100.f) + Direction * 5.f, 50.f, 100.f));
			break;
		}
		case Cap:
		{
			const int32 Current = FMath::RoundToInt(S.GetFrameRateLimit());
			int32 NewCap = Current;
			if (Direction > 0 && Current != 0)
			{
				NewCap = 0;
				for (int32 Limit : Caps)
				{
					if (Limit > Current) { NewCap = Limit; break; }
				}
			}
			else if (Direction < 0)
			{
				NewCap = Caps[0];
				for (int32 Limit : Caps)
				{
					if (Limit > 0 && (Current == 0 || Limit < Current)) { NewCap = Limit; }
				}
			}
			S.SetFrameRateLimit(NewCap);
			break;
		}
		case VSync: S.SetVSyncEnabled(!S.IsVSyncEnabled()); break;
		case Meter: bShowMeter = !bShowMeter; return;
		}
	}
	S.ApplyNonResolutionSettings();
}

void FHCOptions::Confirm(UHCAudio& Audio)
{
	if (!IsReset())
	{
		if (Page == EHCOptionsPage::Sound && Row < BusCount) { Audio.Preview((EHCMixBus)Row); }
		else { Adjust(1, Audio); }
		return;
	}
	bDirty = true;
	if (Page == EHCOptionsPage::Sound)
	{
		Sound = FHCSoundLevels();
		Audio.ApplyMix(Sound);
	}
	else
	{
		Settings& S = *Settings::GetGameUserSettings();
		S.SetOverallScalabilityLevel(1);
		S.SetFrameRateLimit(120.f);
		S.SetVSyncEnabled(false);
		bShowMeter = true;
		S.ApplyNonResolutionSettings();
	}
}
