#!/usr/bin/env bash
# Regenerate every asset from the procedural Blender / numpy generators:
#   characters (body, hair, numbers...), animations, environment, branding and audio.
#   Tools/build_art.sh            # everything
#   Tools/build_art.sh chars      # only characters + animations
#   Tools/build_art.sh env        # only court/hoops/ball/arena/branding
#   Tools/build_art.sh audio      # only sound
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$PROJECT_DIR"
WHAT="${1:-all}"
if [[ "$WHAT" == all || "$WHAT" == chars ]]; then
  echo "=== characters"; "$BLENDER" -b --factory-startup --python-exit-code 1 -P Blender/gen_character.py | grep -E "CHARACTER|PLAYER|Error" || true
  echo "=== animations"; "$BLENDER" -b --factory-startup --python-exit-code 1 -P Blender/gen_anims.py | grep -E "ANIMS|Error" || true
fi
if [[ "$WHAT" == all || "$WHAT" == chars || "$WHAT" == official ]]; then
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P Blender/gen_referee.py
fi
if [[ "$WHAT" == all || "$WHAT" == env ]]; then
  BLENDER="$BLENDER" Blender/build_env.sh
fi
if [[ "$WHAT" == all || "$WHAT" == audio ]]; then
  echo "=== audio"; "$BLENDER_PY" Tools/gen_audio.py
fi
echo "Art rebuilt in Art/Export. Run Tools/import_assets.sh to bring it into Unreal."
