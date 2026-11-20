#pragma once

#include "CoreMinimal.h"

class UHCAudio;
enum class EHCOptionsPage { Closed, Graphics, Sound };
enum class EHCMixBus { Master, Music, Announcer, Crowd, Effects, Interface, Count };

struct FHCSoundLevels
{
	int32 Volume[(int32)EHCMixBus::Count] = {100, 100, 100, 100, 100, 100};
	bool bMuted = false;
	float Gain(EHCMixBus Bus) const;
};

/** Graphics groups are owned by Unreal. The mixer and meter preferences share its per-user ini. */
struct FHCOptions
{
	EHCOptionsPage Page = EHCOptionsPage::Closed;
	int32 Row = 0;
	bool bShowMeter = true;
	FHCSoundLevels Sound;

	void Load();
	void Save();
	void Open(EHCOptionsPage NewPage);
	void Close(UHCAudio& Audio);
	void Move(int32 Direction);
	void Adjust(int32 Direction, UHCAudio& Audio);
	void Confirm(UHCAudio& Audio);
	int32 NumRows() const;
	const TCHAR* Label(int32 Index) const;
	const TCHAR* Help() const;
	FString Value(int32 Index) const;
	int32 VolumePercent(int32 Index) const;
	bool IsReset() const { return Row == NumRows() - 1; }
	static const TCHAR* PresetName();
	static int32 QualityTier();
private:
	bool bDirty = false;
};
