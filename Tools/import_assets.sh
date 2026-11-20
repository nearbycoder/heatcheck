#!/usr/bin/env bash
# Import Art/Export into the Unreal project (/Game/HeatCheck) and build materials + map.
#   Tools/import_assets.sh                          # all steps
#   HC_STEPS=static,materials Tools/import_assets.sh
#   HC_REBUILD_MASTERS=ALL Tools/import_assets.sh   # also rebuild the master material graphs
# Steps: textures, materials, static, skeletal, anims, official, audio, audiomix, map.  Report: Saved/ue_import_report.txt
set -euo pipefail
source "$(dirname "$0")/common.sh"
"$UE_EDITOR" "$UPROJECT" -run=pythonscript -script="$PROJECT_DIR/Tools/ue_import.py" \
  -unattended -nosplash -AllowCommandletRendering > "$PROJECT_DIR/Saved/ue_import.log" 2>&1 || true
tail -3 "$PROJECT_DIR/Saved/ue_import_report.txt"
