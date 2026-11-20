#include "HCTypes.h"

FLinearColor HCRoster::Hex(const TCHAR* InHex)
{
	return FLinearColor(FColor::FromHex(InHex));
}

namespace
{
	FHCPlayerDef P(const TCHAR* First, const TCHAR* Last, const TCHAR* Nick, int32 Num,
		int32 Spd, int32 Sht, int32 Thr, int32 Dnk, int32 Pas, int32 Pow, int32 Stl, int32 Blk, int32 Clu,
		const TCHAR* Skin, EHCHair Hair, const TCHAR* HairCol, EHCBeard Beard, bool bBand, bool bWrist,
		float Height, float Build)
	{
		FHCPlayerDef D;
		D.First = First; D.Last = Last; D.Nick = Nick; D.Number = Num;
		D.Speed = Spd; D.Shoot = Sht; D.Three = Thr; D.Dunk = Dnk; D.Pass = Pas; D.Power = Pow;
		D.Steal = Stl; D.Block = Blk; D.Clutch = Clu;
		D.Skin = HCRoster::Hex(Skin);
		D.Hair = Hair; D.HairColor = HCRoster::Hex(HairCol); D.Beard = Beard;
		D.bHeadband = bBand; D.bWristbands = bWrist; D.Height = Height; D.Build = Build;
		return D;
	}

	TArray<FHCTeamDef> MakeTeams()
	{
		TArray<FHCTeamDef> T;
		auto Team = [&T](const TCHAR* City, const TCHAR* Name, const TCHAR* Abbr, const TCHAR* A, const TCHAR* B, const TCHAR* C) -> FHCTeamDef&
		{
			FHCTeamDef& D = T.AddDefaulted_GetRef();
			D.City = City; D.Name = Name; D.Abbr = Abbr;
			D.Primary = HCRoster::Hex(A); D.Secondary = HCRoster::Hex(B); D.Accent = HCRoster::Hex(C);
			return D;
		};
		{
			FHCTeamDef& D = Team(TEXT("Neon City"), TEXT("Voltage"), TEXT("NEO"), TEXT("FFD60A"), TEXT("111111"), TEXT("00E5FF"));
			D.Players.Add(P(TEXT("Dash"), TEXT("Mercer"), TEXT("Live Wire"), 3, 9, 7, 8, 6, 8, 4, 8, 3, 7,
				TEXT("5C3A21"), EHCHair::Flattop, TEXT("15100C"), EHCBeard::None, true, true, 0.97f, 0.97f));
			D.Players.Add(P(TEXT("Tremont"), TEXT("Baxley"), TEXT("Tank"), 34, 5, 6, 3, 9, 5, 9, 4, 8, 6,
				TEXT("7A4B2A"), EHCHair::Buzz, TEXT("15100C"), EHCBeard::Full, false, false, 1.05f, 1.10f));
		}
		{
			FHCTeamDef& D = Team(TEXT("Bay Harbor"), TEXT("Krakens"), TEXT("BAY"), TEXT("0B7A75"), TEXT("FF6B1A"), TEXT("F2F2F2"));
			D.Players.Add(P(TEXT("Rio"), TEXT("Castellanos"), TEXT("Splash"), 11, 8, 8, 9, 5, 7, 4, 6, 3, 8,
				TEXT("C68642"), EHCHair::Curls, TEXT("1A1410"), EHCBeard::None, false, true, 0.97f, 0.96f));
			D.Players.Add(P(TEXT("Gus"), TEXT("Halvorsen"), TEXT("The Anchor"), 50, 4, 6, 2, 8, 6, 10, 3, 9, 5,
				TEXT("F1C27D"), EHCHair::Bun, TEXT("8A5A2B"), EHCBeard::Goatee, false, false, 1.07f, 1.12f));
		}
		{
			FHCTeamDef& D = Team(TEXT("Red Rock"), TEXT("Scorpions"), TEXT("RRK"), TEXT("B3122E"), TEXT("E9C46A"), TEXT("1B1B1B"));
			D.Players.Add(P(TEXT("Marquis"), TEXT("Delacroix"), TEXT("Sting"), 7, 8, 7, 7, 8, 6, 6, 7, 5, 7,
				TEXT("4A2C1A"), EHCHair::Braids, TEXT("120D0A"), EHCBeard::None, false, true, 1.0f, 1.0f));
			D.Players.Add(P(TEXT("Javier"), TEXT("Montalvo"), TEXT("Desert Storm"), 21, 6, 8, 6, 6, 7, 7, 5, 6, 9,
				TEXT("B5794A"), EHCHair::Mohawk, TEXT("1A1410"), EHCBeard::Goatee, true, false, 1.02f, 1.03f));
		}
		{
			FHCTeamDef& D = Team(TEXT("Frostburg"), TEXT("Yetis"), TEXT("FRB"), TEXT("A9D6F5"), TEXT("0E2A47"), TEXT("FFFFFF"));
			D.Players.Add(P(TEXT("Nils"), TEXT("Brekke"), TEXT("Avalanche"), 15, 6, 7, 7, 7, 6, 8, 5, 7, 6,
				TEXT("F3D1B5"), EHCHair::Buzz, TEXT("C9A36B"), EHCBeard::Full, false, false, 1.04f, 1.06f));
			D.Players.Add(P(TEXT("Kenji"), TEXT("Arakawa"), TEXT("Flurry"), 4, 10, 7, 8, 4, 9, 3, 9, 2, 7,
				TEXT("E8B98F"), EHCHair::Mohawk, TEXT("0F0C0A"), EHCBeard::None, true, true, 0.95f, 0.94f));
		}
		{
			FHCTeamDef& D = Team(TEXT("Steel Valley"), TEXT("Forge"), TEXT("STV"), TEXT("5A6270"), TEXT("FF8C1A"), TEXT("FFD166"));
			D.Players.Add(P(TEXT("Hank"), TEXT("Kowalski"), TEXT("Hammer"), 24, 5, 6, 4, 9, 5, 10, 4, 8, 6,
				TEXT("E0AC69"), EHCHair::Flattop, TEXT("7A2E10"), EHCBeard::None, false, true, 1.06f, 1.12f));
			D.Players.Add(P(TEXT("Andre"), TEXT("Whitfield"), TEXT("Spark Plug"), 9, 9, 8, 7, 7, 7, 5, 8, 4, 7,
				TEXT("6B4226"), EHCHair::Afro, TEXT("120D0A"), EHCBeard::None, true, false, 0.98f, 0.98f));
		}
		{
			FHCTeamDef& D = Team(TEXT("Sunset Coast"), TEXT("Surge"), TEXT("SSC"), TEXT("FF4F79"), TEXT("2B2D9B"), TEXT("2EC4B6"));
			D.Players.Add(P(TEXT("Malik"), TEXT("Fontaine"), TEXT("Riptide"), 1, 9, 7, 8, 9, 6, 5, 7, 5, 8,
				TEXT("3D2616"), EHCHair::Afro, TEXT("0D0907"), EHCBeard::Goatee, false, true, 1.0f, 1.0f));
			D.Players.Add(P(TEXT("Theo"), TEXT("Lindqvist"), TEXT("Breaker"), 33, 5, 6, 3, 8, 6, 9, 4, 9, 5,
				TEXT("F1C27D"), EHCHair::Curls, TEXT("5A3A1E"), EHCBeard::Full, true, false, 1.06f, 1.10f));
		}
		return T;
	}
}

const TArray<FHCTeamDef>& HCRoster::Teams()
{
	static TArray<FHCTeamDef> Teams = MakeTeams();
	return Teams;
}
