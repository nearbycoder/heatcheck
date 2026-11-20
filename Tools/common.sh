# Shared settings for the HEAT CHECK tool scripts (sourced, not executed).
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPROJECT="$PROJECT_DIR/HeatCheck.uproject"
UE_ROOT="${UE_ROOT:-$HOME/UnrealEngine}"
UE_EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
UE_BUILD="$UE_ROOT/Engine/Build/BatchFiles/Mac/Build.sh"
UE_UAT="$UE_ROOT/Engine/Build/BatchFiles/RunUAT.sh"
BLENDER="${BLENDER:-$(command -v blender || echo /Applications/Blender.app/Contents/MacOS/Blender)}"
BLENDER_PY="${BLENDER_PY:-$(ls /Applications/Blender.app/Contents/Resources/*/python/bin/python3* 2>/dev/null | head -1)}"
