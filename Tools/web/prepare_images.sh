#!/usr/bin/env bash
# Web-sized textures/UI (macOS sips). Usage: prepare_images.sh <build_dir> <assets_out_dir>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEX="$ROOT/Art/Export/Textures"; UI="$ROOT/Art/Export/UI"
IMG="$1/img"; OUT="$2"
mkdir -p "$IMG" "$OUT/textures" "$OUT/ui"

# jpeg <src> <dst> <height> <width> <quality>  (sips -z takes height then width)
jpeg() { sips -s format jpeg -s formatOptions "$5" -z "$3" "$4" "$1" --out "$2" >/dev/null; }
# png_fit <src> <dst> <max dimension>  (keeps aspect + alpha; never upscales)
png_fit() {
  local w h; w=$(sips -g pixelWidth "$1" | awk '/pixelWidth/{print $2}'); h=$(sips -g pixelHeight "$1" | awk '/pixelHeight/{print $2}')
  if (( w > $3 || h > $3 )); then sips -s format png -Z "$3" "$1" --out "$2" >/dev/null; else cp "$1" "$2"; fi
}

# textures embedded into the GLBs by postprocess.mjs
jpeg "$TEX/T_Court.png"       "$IMG/T_Court.jpg"       2048 4096 85
jpeg "$TEX/T_Ball.png"        "$IMG/T_Ball.jpg"        512 1024 90
jpeg "$TEX/T_JumboScreen.png" "$IMG/T_JumboScreen.jpg" 1024 2048 88
jpeg "$TEX/T_LedScroll.png"   "$IMG/T_LedScroll.jpg"   256 2048 90
png_fit "$TEX/T_Banners.png"   "$IMG/T_Banners.png"   2048
png_fit "$TEX/T_ShotClock.png" "$IMG/T_ShotClock.png" 2048

# loose FX sprites + UI
for t in T_Flame T_Glow T_Spark T_ShotClock; do cp "$TEX/$t.png" "$OUT/textures/$t.png"; done
png_fit "$UI/UI_Logo.png" "$OUT/ui/UI_Logo.png" 1024
for t in BAY FRB NEO RRK SSC STV; do png_fit "$UI/UI_Team_$t.png" "$OUT/ui/UI_Team_$t.png" 256; done
echo "IMAGES_OK"
