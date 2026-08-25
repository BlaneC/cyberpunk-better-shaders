#!/usr/bin/env bash
# Bisect a "swap HIT but nothing changed on screen" result.
#
#   ./dev/bisect_null.sh          # install the ungated force-tint
#
# Everything the path tracer shades goes blazing red, with no gate and no
# class test, at all six diffuse triples (primary AND env).
#
#   screen turns red  -> the raygen runs; the class gate is the problem
#   screen unchanged  -> this raygen is NOT executing. Path tracing is off,
#                        or the game is using a different raygen. Check
#                        Settings > Graphics > Ray Tracing > Path Tracing.
#                        A HIT only proves the module was CREATED, never that
#                        it was dispatched.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$MOD_DIR/dev/hunt_hair_class.sh" --forcetint
