using UnrealBuildTool;
using System.Collections.Generic;

public class HeatCheckEditorTarget : TargetRules
{
	public HeatCheckEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V8;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_9;
		ExtraModuleNames.Add("HeatCheck");
	}
}
