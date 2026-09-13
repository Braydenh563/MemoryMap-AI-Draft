# Common tasks. Run `make help` to see them.
# (Uses whatever `python`/`pip` are on your PATH — activate your venv first.)

.DEFAULT_GOAL := help
.PHONY: help install install-locked lock run desktop test eval lint format check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies + the app (editable)
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	pip install -e .

lock: ## Pin exact versions into requirements.lock.txt (needs pip-tools)
	python -m pip install --upgrade pip-tools
	pip-compile --output-file=requirements.lock.txt requirements.txt

install-locked: ## Install the exact versions from the lockfile
	python -m pip install --upgrade pip
	pip install -r requirements.lock.txt
	pip install -e .

run: ## Start the app at http://localhost:8000
	python -m memorymap

desktop: ## Start the app in its own window (needs pywebview)
	python -m memorymap --desktop

test: ## Run the test suite (fully offline)
	python -m pytest

eval: ## Score the golden agent asks against a real local model (PLAN.md A6)
	PYTHONPATH=src python scripts/eval.py

lint: ## Lint with ruff (matches CI)
	ruff check .

format: ## Auto-format with ruff
	ruff format .

check: lint test ## Lint then test — run this before pushing
