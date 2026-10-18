SHELL := /bin/bash
.DEFAULT_GOAL := help

PY := uv run

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies (uv sync)
	uv sync

.PHONY: up
up: ## Start local infrastructure (postgres+pgvector, langfuse, mailhog)
	docker compose up -d

.PHONY: down
down: ## Stop local infrastructure
	docker compose down

.PHONY: db-up
db-up: ## Run database migrations
	$(PY) python -m andes.cli migrate

.PHONY: seed
seed: ## Load catalog/seed data
	$(PY) python -m andes.cli seed

.PHONY: run
run: ## Run the FastAPI gateway
	$(PY) uvicorn andes.apps.api.main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: run-booking
run-booking: ## Run the mock business API
	$(PY) uvicorn andes.booking_api.app:app --host 0.0.0.0 --port 8080 --reload

.PHONY: test
test: ## Unit + integration tests
	$(PY) pytest tests/unit tests/integration

.PHONY: test-unit
test-unit: ## Unit tests only
	$(PY) pytest tests/unit

.PHONY: test-integration
test-integration: ## Integration tests only
	$(PY) pytest tests/integration

.PHONY: test-load
test-load: ## Load tests (Locust)
	$(PY) locust -f tests/load/locustfile.py --headless -u 20 -r 2 --run-time 1m --host http://localhost:8000

.PHONY: test-adversarial
test-adversarial: ## Adversarial / red-team tests (promptfoo)
	npx --yes promptfoo@latest eval -c tests/adversarial/promptfooconfig.yaml

.PHONY: eval
eval: ## Retrieval / RAG evaluation (offline)
	$(PY) python evals/ragas_eval.py

.PHONY: mcp
mcp: ## Run the MCP server over stdio
	$(PY) python -m andes.mcp_server.server

.PHONY: lint
lint: ## Lint + format check
	$(PY) ruff check src tests
	$(PY) ruff format --check src tests

.PHONY: fmt
fmt: ## Auto-format
	$(PY) ruff check --fix src tests
	$(PY) ruff format src tests

.PHONY: typecheck
typecheck: ## Static type check
	$(PY) mypy

.PHONY: ollama-pull
ollama-pull: ## Pull the default local model
	ollama pull qwen2.5:14b

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
