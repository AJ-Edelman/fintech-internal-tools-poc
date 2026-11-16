PYTHON ?= $(shell command -v python3.11 2>/dev/null || ls $(HOME)/.pyenv/versions/3.11*/bin/python 2>/dev/null | head -1 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
APP_DB ?= data/app.db
SCALE_DB ?= data/scale.db
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: setup seed run test verify seed-scale test-scale access-review

$(PY): requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt
	@touch $(PY)

setup: $(PY)
	APP_DB=$(APP_DB) $(PY) scripts/migrate.py

seed: $(PY)
	APP_DB=$(APP_DB) $(PY) -m app.seed demo

run: $(PY)
	APP_DB=$(APP_DB) $(PY) -m uvicorn app.main:create_app --factory --host $(HOST) --port $(PORT)

test: $(PY)
	$(PY) -m pytest -q

verify: test
	$(PY) scripts/verify_restart.py

seed-scale: $(PY)
	$(PY) -m app.seed scale --db $(SCALE_DB)

test-scale: $(PY)
	SCALE_DB=$(SCALE_DB) $(PY) -m pytest -q tests/test_scale.py

access-review: $(PY)
	APP_DB=$(APP_DB) $(PY) scripts/access_review.py
