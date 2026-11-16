.PHONY: help lint test test-cov populate validate clean show-format show-data

VENV_BIN := $(shell if [ -d ".venv/bin" ]; then echo ".venv/bin/"; fi)
PYTHON := PYTHONPATH=src:tools:. $(VENV_BIN)python3
PYTEST := $(VENV_BIN)pytest
TOOLS := $(PYTHON) -m tools

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

show-format: ## Display the standard SDK response format
	@$(PYTHON) utils/show_format.py

show-data: ## Pretty-print a response file. Usage: make show-data tmp/file.json
	@$(PYTHON) utils/show_format.py $(filter-out $@,$(MAKECMDGOALS))

populate: ## Populate API data from registry sources
	$(TOOLS).populate $(ARGS)

populate-force: ## Force reprocess all API data
	$(TOOLS).populate --force-reprocess $(ARGS)

validate: ## Validate generated data integrity
	$(TOOLS).validate

clean: ## Clean build artifacts and caches
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
