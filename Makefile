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

# Deploy. GAME_DIR defaults to the dev scripts' library; override on the
# command line. Existing CET + red4ext dirs are backed up first.
GAME_DIR    ?= /mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077
INSTALL_DIR ?= $(HOME)/.local/lib/callisto
KERNELS     := $(wildcard dev/kernels/kernel.*.bin)
CET_LIVE     = $(GAME_DIR)/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS

.PHONY: layer release check install
layer: libVkLayer_callisto_spvswap.so
libVkLayer_callisto_spvswap.so: swap_layer.c
	gcc -shared -fPIC -O2 -Wall -o $@ $< -ldl -lpthread
	cp -f $@ release/vulkan/

release: check
	cp -f $(LUA) $(CET_DST)/
	cp -f kernel.bin $(R4E_DST)/kernel.bin
	mkdir -p $(R4E_DST)/kernels
	cp -f $(KERNELS) $(R4E_DST)/kernels/

# make install: release/ -> the game dir + the layer .so -> $(INSTALL_DIR).
# Does NOT touch brdf_params.txt (the player's switches), swaps, or caches;
# sync_settings.sh evicts the pipeline caches itself on the next launch if
# the payload changed. Before 44 nothing deployed the sources and the game
# ran a sync_settings.sh two commits stale.
#
# detail_engine.txt is SEEDED, NOT SHIPPED, and it is deliberately kept out of
# release/game/ so the `cp -a` above can never reach it (82). The four engine
# panels each write their own <name>_engine.txt from M.save(), so those files
# are player state in exactly the same sense brdf_params.txt is -- clobbering
# one on every deploy would throw away tuning mid-session. hair/pt/skin got
# theirs the first time someone touched a widget; the detail panel had never
# been opened, so its file never existed, so load() bailed on a missing file
# every launch and `enabled` stayed false with all 22 denoiser knobs at engine
# stock (79 section 7). Copy-if-absent gives it a first birth and then never
# touches it again. Delete the live file to re-seed from the repo copy.
install: release layer
	@test -f "$(GAME_DIR)/bin/x64/Cyberpunk2077.exe" || { echo "GAME_DIR='$(GAME_DIR)' is not a Cyberpunk install"; exit 1; }
	@stamp=$$(date +%Y%m%d-%H%M%S); b="$(GAME_DIR)/.callisto_backup/$$stamp"; mkdir -p "$$b"; \
	cp -a "$(GAME_DIR)/bin/x64/plugins/cyber_engine_tweaks/mods/CallistoSSS" "$$b/cet" 2>/dev/null || true; \
	cp -a "$(GAME_DIR)/red4ext/plugins/CallistoSSS" "$$b/red4ext" 2>/dev/null || true; \
	cp -a release/game/. "$(GAME_DIR)/"; \
	if [ -e "$(CET_LIVE)/detail_engine.txt" ]; then \
		echo "detail_engine.txt: already present, left alone (player state)"; \
	else \
		cp -f detail_engine.txt "$(CET_LIVE)/detail_engine.txt" && \
		echo "detail_engine.txt: SEEDED -- denoiser panel is now enabled (82)"; \
	fi; \
	mkdir -p "$(INSTALL_DIR)"; cp -f libVkLayer_callisto_spvswap.so "$(INSTALL_DIR)/"; \
	echo "installed -> $(GAME_DIR) (backup: $$b); layer -> $(INSTALL_DIR)"

check:
	@for f in $(LUA); do luac -p $$f || exit 1; done
	@for f in $(R4E_DST)/sync_settings.sh release/install.sh release/uninstall.sh dev/*.sh; do bash -n $$f || exit 1; done
	@echo ok
