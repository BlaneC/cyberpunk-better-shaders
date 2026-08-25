#!/bin/sh
# Cross-build the RED4ext plugin (runs under Proton, so it's a Windows DLL).
# Prereq: sdk/ = shallow clone of https://github.com/WopsS/RED4ext.SDK
set -e
cd "$(dirname "$0")"
python3 -c "
b=open('../../evidence/sss_kernel_texture.bin','rb').read()[:64]
print('static const unsigned char kFingerprint[64] = {'+','.join(str(x) for x in b)+'};')" > fingerprint.h
x86_64-w64-mingw32-g++ -shared -std=c++20 -O2 -static -Isdk/include -Ishim \
  -o CallistoSSS.dll main.cpp -ld3d12
echo built CallistoSSS.dll
