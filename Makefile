# pynfcreader — relay workflow helpers
#
# Quick start:
#   make help                 # list every target
#   make dev                  # install the package (editable) + test tooling
#   make test                 # run the relay unit tests (no hardware)
#   make build END=usb        # build HF_CARDHOPPER firmware for the USB end
#   make flash FLASH_PORT=/dev/ttyACM0
#   make wsl-attach           # (WSL) attach USB Proxmark3 via usbipd
#   make start                # run the relay in the background
#   make stop
#
# Override any variable on the command line, e.g.:
#   make start CARD_PORT=/dev/ttyACM0 READER_PORT=tcp:172.20.0.1:5555

# ---- configuration (override on the command line) --------------------------
PYTHON      ?= python3
PIP         ?= $(PYTHON) -m pip

# Relay runtime
RELAY       ?= $(PYTHON) -m pynfcreader.relay
CARD_PORT   ?= /dev/ttyACM0
READER_PORT ?= /dev/rfcomm0
TAG_TYPE    ?= 1
FWI         ?= 14
SFGI        ?= 0
RELAY_EXTRA ?=
RELAY_ARGS  ?= --card-port $(CARD_PORT) --reader-port $(READER_PORT) \
               --tag-type $(TAG_TYPE) --fwi $(FWI) --sfgi $(SFGI)
PID_FILE    ?= .relay.pid
LOG_FILE    ?= relay.log

# Proxmark3 firmware (separate RfidResearchGroup/proxmark3 checkout)
PM3_DIR        ?= ../proxmark3
PM3_PLATFORM   ?= PM3GENERIC
PM3_STANDALONE ?= HF_CARDHOPPER
FLASH_PORT     ?=

# Firmware end selected by `make build` / `make flash`: usb | bt
END ?= usb

RELAY_TESTS = tests/test_cardhopper_link.py tests/test_cardhopper_relay.py \
              tests/test_wsl_usbipd.py tests/test_relay_detect.py

.DEFAULT_GOAL := help

.PHONY: help install dev test lint package clean \
        run start stop status list-devices \
        wsl-attach wsl-list \
        build flash fw-build-usb fw-build-bt fw-flash fw-clean

# ---- help ------------------------------------------------------------------
help: ## Show this help
	@echo "pynfcreader relay — make targets:"
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Key variables: CARD_PORT READER_PORT FWI SFGI TAG_TYPE PM3_DIR FLASH_PORT END"

# ---- Python / host ---------------------------------------------------------
install: ## Install the package (editable) with runtime deps
	$(PIP) install -e .

dev: ## Install editable + test tooling (pytest, pyserial)
	$(PIP) install -e . pytest pyserial

test: ## Run the relay unit tests (no hardware required)
	$(PYTHON) -m pytest $(RELAY_TESTS) -q

lint: ## Lint the relay package (ruff or flake8 if installed)
	@if command -v ruff >/dev/null 2>&1; then ruff check pynfcreader/relay; \
	elif command -v flake8 >/dev/null 2>&1; then flake8 pynfcreader/relay; \
	else echo "no linter installed (pip install ruff) — skipping"; fi

package: ## Build the Python sdist + wheel
	@$(PYTHON) -m build 2>/dev/null || $(PYTHON) setup.py sdist bdist_wheel

clean: ## Remove build artifacts, caches, relay pid/log
	rm -rf build dist *.egg-info .pytest_cache $(PID_FILE) $(LOG_FILE)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ---- relay runtime ---------------------------------------------------------
list-devices: ## List detected Proxmark3 serial ports and USB serials
	$(RELAY) --list-devices

run: ## Run the relay in the foreground (Ctrl-C to stop)
	$(RELAY) $(RELAY_ARGS) $(RELAY_EXTRA)

start: ## Start the relay in the background (PID file + log)
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "relay already running (PID $$(cat $(PID_FILE)))"; exit 1; fi
	@nohup $(RELAY) $(RELAY_ARGS) $(RELAY_EXTRA) >$(LOG_FILE) 2>&1 & echo $$! >$(PID_FILE)
	@sleep 1; echo "relay started (PID $$(cat $(PID_FILE))), logging to $(LOG_FILE)"

stop: ## Stop the background relay
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null && echo "relay stopped"; rm -f $(PID_FILE); \
	else echo "relay not running (no $(PID_FILE))"; fi

status: ## Show whether the background relay is running
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "relay running (PID $$(cat $(PID_FILE)))"; \
	else echo "relay not running"; fi

# ---- WSL (usbipd) ----------------------------------------------------------
wsl-attach: ## (WSL) bind + attach USB Proxmark3 devices via usbipd-win
	$(PYTHON) -m pynfcreader.relay.wsl --bind

wsl-list: ## (WSL) list Proxmark3 USB devices visible to usbipd
	$(PYTHON) -m pynfcreader.relay.wsl --list

# ---- Proxmark3 firmware (needs PM3_DIR + arm-none-eabi toolchain) -----------
build: fw-build-$(END) ## Build HF_CARDHOPPER firmware for one end (END=usb|bt)

flash: fw-flash ## Flash the built firmware image (set FLASH_PORT=/dev/ttyACM0)

fw-build-usb: ## Build firmware for the USB end (-DCARDHOPPER_USB)
	@test -d "$(PM3_DIR)" || { echo "PM3_DIR='$(PM3_DIR)' not found — set PM3_DIR=/path/to/proxmark3"; exit 1; }
	@if [ -f "$(PM3_DIR)/Makefile.platform" ] && [ ! -f "$(PM3_DIR)/Makefile.platform.bak" ]; then \
		cp "$(PM3_DIR)/Makefile.platform" "$(PM3_DIR)/Makefile.platform.bak" && echo "backed up Makefile.platform -> Makefile.platform.bak"; fi
	@printf 'PLATFORM=%s\nPLATFORM_EXTRAS=\nSTANDALONE_PLATFORM_DEFS+=-DCARDHOPPER_USB\n' "$(PM3_PLATFORM)" > "$(PM3_DIR)/Makefile.platform"
	@echo "configured USB build: PLATFORM=$(PM3_PLATFORM), -DCARDHOPPER_USB"
	cd $(PM3_DIR) && make clean && make STANDALONE=$(PM3_STANDALONE) -j

fw-build-bt: ## Build firmware for the Bluetooth end (PLATFORM_EXTRAS=BTADDON)
	@test -d "$(PM3_DIR)" || { echo "PM3_DIR='$(PM3_DIR)' not found — set PM3_DIR=/path/to/proxmark3"; exit 1; }
	@if [ -f "$(PM3_DIR)/Makefile.platform" ] && [ ! -f "$(PM3_DIR)/Makefile.platform.bak" ]; then \
		cp "$(PM3_DIR)/Makefile.platform" "$(PM3_DIR)/Makefile.platform.bak" && echo "backed up Makefile.platform -> Makefile.platform.bak"; fi
	@printf 'PLATFORM=%s\nPLATFORM_EXTRAS=BTADDON\n' "$(PM3_PLATFORM)" > "$(PM3_DIR)/Makefile.platform"
	@echo "configured Bluetooth build: PLATFORM=$(PM3_PLATFORM), PLATFORM_EXTRAS=BTADDON"
	cd $(PM3_DIR) && make clean && make STANDALONE=$(PM3_STANDALONE) -j

fw-flash: ## Flash the last-built fullimage (flashing is always over USB)
	@test -d "$(PM3_DIR)" || { echo "PM3_DIR='$(PM3_DIR)' not found — set PM3_DIR=/path/to/proxmark3"; exit 1; }
	cd $(PM3_DIR) && ./pm3-flash-fullimage $(if $(FLASH_PORT),-p $(FLASH_PORT),)

fw-clean: ## Run `make clean` in the Proxmark3 tree
	@test -d "$(PM3_DIR)" || { echo "PM3_DIR='$(PM3_DIR)' not found"; exit 1; }
	cd $(PM3_DIR) && make clean
