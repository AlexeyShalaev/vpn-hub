#!/bin/bash
# Вкомпоновывает запись тура в «плавающее окно» на градиентном фоне с тенью → MP4 + GIF.
# Вход:  .build/out/*.webm (из record.mjs) + .build/assets/*.png (из gen-assets.mjs)
# Выход: docs/assets/reel/reel.mp4 + reel.gif (переопределяется через $DIST_DIR).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
BUILD="${BUILD_DIR:-$HERE/.build}"
A="${ASSETS_DIR:-$BUILD/assets}"
DIST="${DIST_DIR:-$ROOT/docs/assets/reel}"
mkdir -p "$DIST"
REC=$(ls "$BUILD"/out/*.webm | head -1)
echo "recording: $REC"

# MP4: окно(1600x1000, скруглённое) на фоне(1920x1080) + мягкая тень
ffmpeg -y -i "$REC" -i "$A/bg.png" -i "$A/mask.png" -i "$A/shadow.png" -filter_complex "
[0:v]scale=1600:1000,setsar=1,fps=30[rec];
[rec][2:v]alphamerge[win];
[1:v][3:v]overlay=0:0[bgsh];
[bgsh][win]overlay=(W-w)/2:(H-h)/2[v]
" -map "[v]" -c:v libx264 -pix_fmt yuv420p -crf 20 -preset medium -movflags +faststart "$DIST/reel.mp4" -loglevel error
echo "MP4 done: $(du -h "$DIST/reel.mp4" | cut -f1)"

# GIF для README (760px, 12fps, палитра — компактнее для встраивания)
ffmpeg -y -i "$DIST/reel.mp4" -vf "fps=12,scale=760:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=2" "$DIST/reel.gif" -loglevel error
echo "GIF done: $(du -h "$DIST/reel.gif" | cut -f1)"
echo "COMPOSE_DONE → $DIST"
