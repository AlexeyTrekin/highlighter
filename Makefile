# Host-native entry points; the project runs directly on the machine (spec/004_stack.md).
# Agents invoke these through `agent-make`; see AGENTS.md MAKE COMMAND POLICY.
#
# `agent-make` verifies this file byte-for-byte against origin/master and blocks every
# invocation while they differ, so a change here costs a human-reviewed merge before any
# branch can run tests again. The target set is therefore complete ahead of the code:
# `run` and `bench` call CLI commands that arrive in WAL phases 3.1 and 2.2 and fail with
# `No such command` until then. That is expected, not a regression.

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
STAMP := $(VENV)/.install-stamp

# Project directory used by `make run`; humans override on the command line.
# Agents cannot pass VAR=val (agent-make.allowed-vars is empty) and should call
# `.venv/bin/hlreel review <dir>` directly instead.
PROJECT ?= projects/default

.PHONY: help venv doctor test utest itest lint fmt run bench clean

help:
	@echo "venv    create .venv and install the project with dev extras"
	@echo "doctor  check host prerequisites (python, ffmpeg+libvidstab, ffprobe)"
	@echo "test    full test suite"
	@echo "utest   unit tests only"
	@echo "itest   integration tests only"
	@echo "lint    ruff check + format check"
	@echo "fmt     ruff format (writes)"
	@echo "run     start the review server on the host           (from WAL 3.1)"
	@echo "bench   score candidate ranking against human verdicts (from WAL 2.2)"
	@echo "clean   remove .venv, caches and build artifacts"

venv: $(STAMP)

$(STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"
	@touch $(STAMP)

doctor: venv
	$(BIN)/hlreel doctor

test: venv
	$(BIN)/python -m pytest tests -q

utest: venv
	$(BIN)/python -m pytest tests/unit -q

itest: venv
	$(BIN)/python -m pytest tests/it -q

lint: venv
	$(BIN)/ruff check app tests
	$(BIN)/ruff format --check app tests

fmt: venv
	$(BIN)/ruff format app tests

run: venv
	$(BIN)/hlreel review $(PROJECT)

bench: venv
	$(BIN)/hlreel bench tests/fixtures/ground_truth

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
