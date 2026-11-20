using UnrealBuildTool;
using System.Collections.Generic;

public class HeatCheckTarget : TargetRules
{
	public HeatCheckTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V8;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_9;
		ExtraModuleNames.Add("HeatCheck");
	}
}
