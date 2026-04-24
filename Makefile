.PHONY: help venv install test lint run-server clean

VENV ?= .venv
PY   ?= python3
PIP  := $(VENV)/bin/pip

help:
	@echo "Targets:"
	@echo "  venv         Create a local virtual environment in .venv"
	@echo "  install      Install cloud-alert-hub with dev extras (editable)"
	@echo "  test         Run the test suite"
	@echo "  lint         Run ruff across src/ and tests/"
	@echo "  run-server   Start the local FastAPI dev server"
	@echo "  clean        Remove caches, build artefacts, and the venv"

venv:
	$(PY) -m venv $(VENV)

install:
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check src tests

run-server:
	$(VENV)/bin/uvicorn examples.local-dev.app:app --reload

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__ *.egg-info src/*.egg-info
