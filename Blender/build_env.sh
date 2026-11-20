#!/usr/bin/env bash
# HEAT CHECK - regenerate all ENVIRONMENT art (court, hoops, ball, arena + crowd, branding),
# render the verification previews and validate the exports.
#
#   Blender/build_env.sh                 # everything (~1 minute on Apple silicon)
#   BLENDER=/path/to/blender Blender/build_env.sh
#   Blender/build_env.sh --no-preview    # skip the assembled-scene preview renders
#
# Order matters: the ball texture is used by the 3D title logo, and the team badges are used by the
# arena banners. Each generator also renders its own previews into Art/Previews/.
set -euo pipefail
cd "$(dirname "$0")/.."
BLENDER="${BLENDER:-/opt/homebrew/bin/blender}"
PREVIEW=1
[[ "${1:-}" == "--no-preview" ]] && PREVIEW=0
LOGDIR="${TMPDIR:-/tmp}/heatcheck_env_logs"
mkdir -p "$LOGDIR"

run() {
  local script="$1"
  echo "=== ${script}"
  local t0=$SECONDS
  local log="$LOGDIR/${script%.py}.log"
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P "Blender/${script}" > "$log" 2>&1 \
    || { echo "!!! ${script} failed, see $log"; tail -n 30 "$log"; exit 1; }
  grep -E "^(WROTE|EXPORTED|MESH|RENDERED|STANCHION|CHECK|TOTAL|\[arena|\[court)" "$log" || true
  echo "    (${script} took $((SECONDS - t0))s)"
}

run gen_ball.py
run gen_branding.py
run gen_court.py
run gen_hoop.py
run gen_arena.py
if [[ $PREVIEW -eq 1 ]]; then
  run preview_env.py
fi
run check_env.py
echo "Environment art rebuilt."
