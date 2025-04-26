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
  diri=$(dirname $i)
  echo "Processing $basei"
  sudo docker run --rm -it --runtime=nvidia --volume $PWD:/workspace willprice/nvidia-ffmpeg -hwaccel_device 0 -hwaccel cuvid -c:v mpeg2_cuvid -i "$i" -c:v h264_nvenc -rc:v vbr -cq:v 29 -b:v 0 "color/${basei/.mpeg/.mp4}"
  sudo chown -R $USER:$USER color
done
echo Done