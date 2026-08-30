#!/usr/bin/env bash
# Pull the N newest photo-mode captures into a rung directory, in SHOOTING
# order. N is the number of names given.
#
#   bash a-b-testing/collect.sh L1-noise-floor S1 S2 S3
#
# Shoot the scenes in the order you name them here. Prints mtimes so a
# mis-ordered or stale pickup is obvious before any number is computed.
set -eu
cd "$(dirname "$0")/.."
SHOTS="/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/compatdata/1091500/pfx/drive_c/users/steamuser/Pictures/Cyberpunk 2077"

dest="a-b-testing/$1"; shift
[ -d "$dest" ] || { echo "no such rung dir: $dest" >&2; exit 1; }
n=$#
mapfile -t src < <(ls -1t "$SHOTS"/photomode_*.png | head -n "$n" | tac)
[ "${#src[@]}" -eq "$n" ] || { echo "found ${#src[@]} captures, wanted $n" >&2; exit 1; }

i=0
for name in "$@"; do
  cp -- "${src[$i]}" "$dest/$name.png"
  printf '%-4s <- %s  (%s)\n' "$name" "$(basename "${src[$i]}")" \
      "$(date -r "${src[$i]}" +%H:%M:%S)"
  i=$((i+1))
done

# Pin the game settings for this capture set. The game writes UserSettings.json
# on Apply, while running, so its mtime against the capture mtimes settles what
# was in force -- see handoff/49 section 0.1 and dev/ab_settings.py. The
# 2026-08-30 regime break (handoff/46 section 13) was an unlogged mid-session
# settings change, and two RR-off attempts silently ran RR on; this is the
# check that would have caught both.
echo
python3 dev/ab_settings.py check "$dest" || true
