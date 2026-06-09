# PartyHams Logger — developer Makefile
#
# Quick start:
#   make run      # set up everything and launch the app
#   make test     # run the test suite
#   make help     # list all targets

VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
STAMP := $(VENV)/.installed

# Bootstrap interpreter for the venv — prefer a 3.12/3.13/3.14 (the system
# python may be too old). Override with: make PYTHON=/path/to/python3.12 run
PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3.13 2>/dev/null || command -v python3.14 2>/dev/null)

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# Create the virtualenv (its python binary is the target file).
$(PY):
	@test -n "$(PYTHON)" || { \
		echo "ERROR: no Python >=3.12 found."; \
		echo "Install one, e.g.:  brew install python@3.12"; \
		echo "or point at yours:  make PYTHON=/path/to/python3.12 run"; \
		exit 1; }
	@echo ">> creating venv with $(PYTHON)"
	@$(PYTHON) -m venv $(VENV)

# Install the app + dev tooling once; re-runs if pyproject.toml changes.
$(STAMP): $(PY) pyproject.toml
	@echo ">> installing partyhams + dev deps (PySide6, pytest, ruff)"
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -e ".[dev]"
	@touch $(STAMP)

.PHONY: setup
setup: $(STAMP) ## Create the venv and install the app + dev deps

.PHONY: run
run: $(STAMP) ## Launch the app (sets up the venv first if needed)
	@echo ">> launching PartyHams Logger"
	@$(PY) -m partyhams

.PHONY: spike
spike: $(STAMP) ## Run the P2P sync spike (e.g. make spike CALL=W7ABC)
	@test -n "$(CALL)" || { echo "set CALL, e.g.: make spike CALL=W7ABC"; exit 1; }
	@$(PY) -m partyhams.net.spike --call $(CALL)

.PHONY: rig-spike
rig-spike: $(STAMP) ## Watch live freq/mode from rigctld (make rig-spike [HOST=x PORT=y])
	@$(PY) -m partyhams.radio.spike $(if $(HOST),--host $(HOST)) $(if $(PORT),--port $(PORT))

.PHONY: flex-spike
flex-spike: $(STAMP) ## Discover/watch a FlexRadio natively (make flex-spike [HOST=ip])
	@$(PY) -m partyhams.radio.flex_spike $(if $(HOST),--host $(HOST)) $(if $(PORT),--port $(PORT))

.PHONY: test
test: $(STAMP) ## Run the test suite
	@$(PY) -m pytest -q

.PHONY: lint
lint: $(STAMP) ## Lint with ruff
	@$(PY) -m ruff check src tests

.PHONY: format
format: $(STAMP) ## Auto-format and fix with ruff
	@$(PY) -m ruff format src tests
	@$(PY) -m ruff check --fix src tests

.PHONY: check
check: lint test ## Lint and test (what CI will run)

# ---- Packaging (PyInstaller; see docs/PACKAGING.md) ---------------------
# Builds run on the host OS/arch only — there is no cross-compilation. The
# packaging extra (PyInstaller) is installed on demand into the dev venv.
PKG_STAMP := $(VENV)/.packaging

$(PKG_STAMP): $(STAMP)
	@echo ">> installing packaging deps (PyInstaller)"
	@$(PIP) install -q -e ".[packaging]"
	@touch $(PKG_STAMP)

.PHONY: package
package: $(PKG_STAMP) ## Build a standalone app for THIS OS (-> dist/)
	@$(PY) -m PyInstaller --noconfirm --clean packaging/partyhams.spec
	@echo ">> built dist/ (see docs/PACKAGING.md)"

.PHONY: package-mac-universal
package-mac-universal: $(PKG_STAMP) ## macOS universal2 .app (Intel + Apple Silicon)
	@$(PY) -m PyInstaller --noconfirm --clean --target-arch universal2 packaging/partyhams.spec

.PHONY: package-appimage
package-appimage: package ## Linux AppImage (needs linuxdeploy + appimagetool)
	@bash packaging/build-appimage.sh

.PHONY: package-deb
package-deb: package ## Linux .deb (needs fpm)
	@bash packaging/build-linux-pkg.sh deb

.PHONY: package-rpm
package-rpm: package ## Linux .rpm (needs fpm)
	@bash packaging/build-linux-pkg.sh rpm

.PHONY: clean
clean: ## Remove caches and build artifacts (keeps the venv)
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .ruff_cache .mypy_cache build dist src/*.egg-info
	@echo ">> cleaned"

.PHONY: distclean
distclean: clean ## Also remove the virtualenv
	@rm -rf $(VENV)
	@echo ">> removed $(VENV)"
