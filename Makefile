.PHONY: help lint test test-cov benchmark clean

VENV_BIN := $(shell if [ -d ".venv/bin" ]; then echo ".venv/bin/"; fi)
PYTHON := PYTHONPATH=src:. $(VENV_BIN)python3
PYTEST := $(VENV_BIN)pytest

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff / linter
	ruff check .

test: ## Run test suite
	$(PYTEST) -v tests/

test-cov: ## Run test suite with coverage
	$(PYTEST) --cov=mapi --cov-report=term-missing tests/

benchmark: ## Run execution benchmarks and call budget verification
	$(PYTHON) -m tests.benchmark_profile

clean: ## Clean build artifacts and caches
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
