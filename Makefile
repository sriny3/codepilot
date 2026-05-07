PY ?= python
PIP ?= $(PY) -m pip

.PHONY: install install-dev test test-unit test-cov lint format type clean run doctor

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

test:
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit

test-cov:
	$(PY) -m pytest --cov=codepilot --cov-report=term-missing --cov-fail-under=85

lint:
	$(PY) -m ruff check codepilot tests

format:
	$(PY) -m ruff format codepilot tests

type:
	$(PY) -m mypy codepilot

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist *.egg-info

run:
	$(PY) -m codepilot run

doctor:
	$(PY) -m codepilot doctor
