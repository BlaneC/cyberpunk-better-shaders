# CallistoSSS -- keep the shipped copies in release/ in step with the sources.
#
#   make layer     build libVkLayer_callisto_spvswap.so and copy it to release/vulkan/
#   make release   copy the CET Lua + kernel.bin + sync_settings.sh into release/
#   make check     luac -p every Lua file, bash -n every shell script
#
# The root copies are the SOURCE. release/game/... is what install.sh ships.
CET_DST  := release/game/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS
R4E_DST  := release/game/red4ext/plugins/CallistoSSS
LUA      := init.lua hair_engine.lua skin_engine.lua pt_engine.lua detail_engine.lua

.PHONY: layer release check
layer: libVkLayer_callisto_spvswap.so
libVkLayer_callisto_spvswap.so: swap_layer.c
	gcc -shared -fPIC -O2 -Wall -o $@ $< -ldl -lpthread
	cp -f $@ release/vulkan/

release: check
	cp -f $(LUA) $(CET_DST)/
	cp -f kernel.bin $(R4E_DST)/kernel.bin

check:
	@for f in $(LUA); do luac -p $$f || exit 1; done
	@for f in $(R4E_DST)/sync_settings.sh release/install.sh release/uninstall.sh dev/*.sh; do bash -n $$f || exit 1; done
	@echo ok
