#!/bin/sh
# Build the SPIR-V swap layer (native Linux .so -- vkd3d-proton calls the
# native Vulkan loader even under Proton).
set -e
cd "$(dirname "$0")"
gcc -shared -fPIC -O2 -Wall -Wextra \
  -o libVkLayer_callisto_spvswap.so swap_layer.c -ldl -lpthread
mkdir -p swaps
echo built libVkLayer_callisto_spvswap.so
