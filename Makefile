SHELL := /bin/bash
DIR   := hype_dca
PYTHON ?= /Library/Frameworks/Python.framework/Versions/3.12/bin/python3
LAUNCHD_LABEL := com.viveksingh.hypedca
LAUNCHD_TEMPLATE := launchd/hypedca.plist.template
LAUNCHD_DEST := $(HOME)/Library/LaunchAgents/$(LAUNCHD_LABEL).plist
LAUNCHD_DOMAIN := gui/$(shell id -u)
REPO_DIR := $(abspath .)

.PHONY: run run-once logs check price bridge launchd-install launchd-uninstall launchd-start launchd-stop launchd-status stop

# Run bot in foreground — logs to terminal and bot.log simultaneously
run:
	cd $(DIR) && $(PYTHON) scheduler.py 2>&1 | tee bot.log

# Run one DCA cycle, then exit — suitable for launchd/cron
run-once:
	cd $(DIR) && $(PYTHON) run_once.py 2>&1 | tee -a bot.log

# Tail live logs (when bot is running in another tab)
logs:
	tail -f $(DIR)/bot.log

# Check Arbitrum + HyperCore USDC balances
check:
	cd $(DIR) && $(PYTHON) check_balances.py

# Show current HYPE price and MA vs threshold
price:
	cd $(DIR) && $(PYTHON) -c "\
from price import fetch_2h_ma; import config; \
p, ma = fetch_2h_ma(); \
print(f'Price: \$\${ p:.4f}  MA: \$\${ ma:.4f}  Threshold: \$\${config.MA_THRESHOLD_USD}  Buy: {ma < config.MA_THRESHOLD_USD}')"

# Show in-flight bridge state (if any)
bridge:
	@[ -f $(DIR)/bridge_state.json ] \
		&& cat $(DIR)/bridge_state.json \
		|| echo "No bridge in flight"

# Install the macOS launchd job: runs make run-once every 3 minutes while awake
launchd-install:
	mkdir -p $(HOME)/Library/LaunchAgents
	sed "s|@REPO_DIR@|$(REPO_DIR)|g" $(LAUNCHD_TEMPLATE) > $(LAUNCHD_DEST)
	plutil -lint $(LAUNCHD_DEST)
	-launchctl bootout $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL) 2>/dev/null
	launchctl bootstrap $(LAUNCHD_DOMAIN) $(LAUNCHD_DEST)
	launchctl kickstart -k $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL)

launchd-uninstall:
	-launchctl bootout $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL) 2>/dev/null
	rm -f $(LAUNCHD_DEST)

launchd-start:
	launchctl kickstart -k $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL)

launchd-stop:
	-launchctl kill TERM $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL)

launchd-status:
	launchctl print $(LAUNCHD_DOMAIN)/$(LAUNCHD_LABEL)
