.PHONY: help install-dev demo compile test lint format-check check

help:
	@echo "MechanistGym development commands"
	@echo "  make install-dev  Install the package and development tools"
	@echo "  make demo         Run the M0 analytic fixture"
	@echo "  make compile      Compile Python sources to catch syntax errors"
	@echo "  make test         Run the standard-library test suite"
	@echo "  make lint         Run Ruff lint checks"
	@echo "  make format-check Check Ruff formatting without modifying files"
	@echo "  make check        Run all local quality gates"

install-dev:
	python -m pip install -e ".[dev]"

demo:
	PYTHONPATH=src python -m mechanistgym

compile:
	python -m compileall -q src tests

test:
	PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v

lint:
	python -m ruff check src tests

format-check:
	python -m ruff format --check src tests

check: compile test lint format-check
