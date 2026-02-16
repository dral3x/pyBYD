#!/bin/bash
set -e

file_name=$(date +dump-%Y_%m_%d-%H_%M_%S.json)

python scripts/dump_all.py --output "$file_name"

echo "============================================================"
echo "  DIFF"
echo "============================================================"

files=($(ls -t dump-*.json | head -2))
if [ ${#files[@]} -ge 2 ]; then
  python scripts/diff_dumps.py "${files[1]}" "${files[0]}"
else
  echo "Need at least 2 dump files to diff"
fi