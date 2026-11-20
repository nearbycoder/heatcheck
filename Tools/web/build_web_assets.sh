#!/usr/bin/env bash
# HEAT CHECK: build the browser (three.js) asset set in web/play/assets from Art/.
#
#   Tools/web/build_web_assets.sh              # full build + verification + preview renders
#   Tools/web/build_web_assets.sh --no-render  # skip the preview PNGs (checks still run)
#
# Needs: blender (5.3) on PATH, node + npm, ffmpeg/ffprobe, python3, macOS sips.
# Steps: Blender exports raw glTF (characters from Art/Blend/*.blend, statics from the FBXs)
# -> textures/UI resized -> gltf-transform post-process (materials, textures, meshopt)
# -> audio -> manifests -> re-import + checks + previews in Blender.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$HERE/.build"
OUT="$ROOT/web/play/assets"
PREV="$HERE/previews"
BLENDER="${BLENDER:-blender}"
RENDER_FLAG=""
[[ "${1:-}" == "--no-render" ]] && RENDER_FLAG="--no-render"

cd "$ROOT"
echo "== node deps"
if [[ ! -d "$HERE/node_modules/@gltf-transform/functions" ]]; then
  (cd "$HERE" && npm install --no-audit --no-fund --silent)
fi

rm -rf "$BUILD" "$OUT"
mkdir -p "$BUILD" "$OUT"

bl() { "$BLENDER" "$@" >"$BUILD/blender.log" 2>&1 || { tail -40 "$BUILD/blender.log"; exit 1; }; }

echo "== blender: player (player_actions.blend + A_Tip from referee.blend)"
bl -b "$ROOT/Art/Blend/player_actions.blend" --python-exit-code 1 -P "$HERE/blender_characters.py" -- \
   player "$BUILD/player_raw.glb" "$BUILD/player_stats.json"
echo "== blender: referee"
bl -b "$ROOT/Art/Blend/referee.blend" --python-exit-code 1 -P "$HERE/blender_characters.py" -- \
   referee "$BUILD/referee_raw.glb" "$BUILD/referee_stats.json"
echo "== blender: court / arena / arena_lite / hoop / ball (FBX)"
bl -b --factory-startup --python-exit-code 1 -P "$HERE/blender_static.py" -- "$BUILD"

echo "== images"
"$HERE/prepare_images.sh" "$BUILD" "$OUT"
echo "== gltf post-process"
node "$HERE/postprocess.mjs" "$BUILD" "$OUT" | grep '^POST'
echo "== audio"
python3 "$HERE/convert_audio.py" "$OUT" | grep -E '^(LOOP|AUDIO_OK)'
echo "== manifests"
python3 "$HERE/make_manifest.py" "$BUILD" "$OUT"

echo "== glTF validator"
node "$HERE/validate.mjs" "$OUT"
echo "== verify (re-import final GLBs in Blender)"
"$BLENDER" -b --factory-startup --python-exit-code 1 -P "$HERE/verify_blender.py" -- "$OUT" "$PREV" $RENDER_FLAG \
  >"$BUILD/verify.log" 2>&1 || { grep -E '^(PASS|FAIL|VERIFY)|Error|Traceback' "$BUILD/verify.log"; exit 1; }
grep -E '^(FAIL|VERIFY)' "$BUILD/verify.log"
[[ -z "$RENDER_FLAG" ]] && echo "previews: $PREV"
du -sh "$OUT"
