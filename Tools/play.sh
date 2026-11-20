#!/usr/bin/env bash
# Play HEAT CHECK (runs the game through the editor binary, no packaging needed).
#   Tools/play.sh                 # windowed 1920x1080
#   Tools/play.sh -fullscreen
#   Tools/play.sh -hcwatch        # jump straight into a CPU vs CPU game
#   Tools/play.sh -hcquarter=2    # 2-minute quarters      -hcbighead  big head mode
set -euo pipefail
source "$(dirname "$0")/common.sh"
ARGS=("-game" "-ResX=1920" "-ResY=1080" "-nosplash")
if [[ " $* " != *" -fullscreen "* ]]; then ARGS+=("-windowed"); fi
exec "$UE_EDITOR" "$UPROJECT" "${ARGS[@]}" "$@"
