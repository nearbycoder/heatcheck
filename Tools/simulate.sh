#!/usr/bin/env bash
# Headless rules / AI soak test: plays a full CPU vs CPU game as fast as possible and prints the box score.
#   Tools/simulate.sh            # 2-minute quarters
#   Tools/simulate.sh 3 -hcautopilot   # 3-minute quarters with P1 driven through the human input path
set -euo pipefail
source "$(dirname "$0")/common.sh"
Q="${1:-2}"; shift || true
MODE="-hcwatch"; [[ " $* " == *" -hcautopilot "* ]] && MODE=""
"$UE_EDITOR" "$UPROJECT" -game -nullrhi -nosound $MODE -hcquarter="$Q" -hcsimexit -benchmark -fps=30 -unattended -nosplash "$@" > /dev/null 2>&1 || true
grep -E "SIM |EVENT" "$HOME/Library/Logs/HeatCheck/HeatCheck.log" | sed 's/.*LogHeatCheck: Display: //' | grep -E "SIM|ON FIRE|STUFFED|Goaltending|Shot clock" 
