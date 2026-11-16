.PHONY: help lint test test-cov populate validate clean

PYTHON := PYTHONPATH=src:tools python3
TOOLS := $(PYTHON) -m tools

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff / linter
	ruff check .

test: ## Run test suite
	pytest -v tests/

test-cov: ## Run test suite with coverage
	pytest --cov=mapi --cov-report=term-missing tests/

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
