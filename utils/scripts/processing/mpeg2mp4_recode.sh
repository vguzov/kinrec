#!/usr/bin/env bash

set -e

cd "$1" || exit 1
if [ -d "color.mpeg2" ]; then
  echo "Color is already recoded, exiting"
  exit 2
fi
mv color color.mpeg2
mkdir color
for i in color.mpeg2/*.mpeg; do
  basei=$(basename $i)
  echo "Processing $basei"
  ffmpeg -i "$i" -c:v libx264 "color/${basei/.mpeg/.mp4}"
done
echo Done