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

# --- watsonx Orchestrate environment (see orchestrate/README.md) ---
WXO_PY ?= $(shell uv tool dir 2>/dev/null)/ibm-watsonx-orchestrate/bin/python
WXO := $(WXO_PY) orchestrate/scripts/wxo.py
WXO_PUSH_FLAGS := $(if $(APPLY),--apply) $(if $(ONLY),--only $(ONLY)) $(if $(UPDATE_SAFE),--update-safe)

.PHONY: wxo-pull
wxo-pull: ## Orchestrate: export the instance into orchestrate/
	$(WXO) pull

.PHONY: wxo-plan
wxo-plan: ## Orchestrate: diff orchestrate/ against the instance
	$(WXO) plan

.PHONY: wxo-push
wxo-push: ## Orchestrate: push changed files (dry run; APPLY=1 to apply, ONLY=agents/X)
	$(WXO) push $(WXO_PUSH_FLAGS)

.PHONY: tools-specs
tools-specs: ## Regenerate build/andes_tools_api.openapi.yaml (tools API) to import in the Orchestrate console
	$(PY) --env-file .env python scripts/gen_tool_specs.py

.PHONY: wxo-connection-creds
wxo-connection-creds: ## Orchestrate: give the andes_tools_api connection the TOOLS_API_KEY from .env (ENV=draft|live)
	@set -a; . ./.env; set +a; \
	$(dir $(WXO_PY))orchestrate connections set-credentials -a andes_tools_api \
		--env $(or $(ENV),draft) --api-key "$$TOOLS_API_KEY"

# --- PoC tools API (src/andes/apps/tools_api) ---
CE_PROJECT ?= andes-poc
CE_APP ?= andes-tools-api
CE_SECRET ?= andes-tools-api

.PHONY: api-run
api-run: ## Tools API locally on :8090 (in-memory unless TOOLS_DATABASE_URL is set)
	TOOLS_API_KEY=$${TOOLS_API_KEY:-dev-key} $(PY) uvicorn andes.apps.tools_api.main:app --port 8090 --reload

.PHONY: api-seed-sql
api-seed-sql: ## Regenerate supabase/seed.sql from the catalog
	$(PY) python scripts/gen_seed_sql.py

.PHONY: db-apply
db-apply: ## Apply supabase/migrations + seed to TOOLS_DATABASE_URL (from .env)
	$(PY) --env-file .env python scripts/db_apply.py

# Hosting: Render free plan (service andes-tools-api, branch feat/poc-tools-api).
# Render reads the public repo without its GitHub app, so a push does NOT deploy:
# push, then `make api-redeploy`. The workspace has NO payment method, so it cannot bill:
# over the limits Render suspends the service instead. It sleeps after 15 min idle
# and takes ~1 min to wake, so run `make api-warm` before testing or a demo.
# The URL lives in .env (TOOLS_API_URL), not in the public repo.
RENDER_SERVICE ?= srv-dbpi6iegekts73a1gu30

.PHONY: api-redeploy
api-redeploy: ## Deploy the pushed HEAD commit to Render and wait for it (needs RENDER_API_KEY in .env)
	@git fetch -q origin && git branch -r --contains HEAD | grep -q . \
		|| { echo "HEAD is not pushed yet: git push first"; exit 1; }
	@set -a; . ./.env; set +a; \
	render deploys create $(RENDER_SERVICE) --commit $$(git rev-parse HEAD) --wait --confirm -o text

.PHONY: api-warm
api-warm: ## Wake the deployed tools API (Render free sleeps when idle) and wait until healthy
	@set -a; . ./.env; set +a; \
	for i in $$(seq 1 24); do \
		if curl -fsS --max-time 10 "$$TOOLS_API_URL/health"; then echo; exit 0; fi; \
		echo "waking up... ($$i)"; sleep 5; \
	done; echo "API did not answer in 2 minutes"; exit 1

# --- Alternative: IBM Code Engine (needs Code Engine access in the IBM account) ---
# Cost caps, applied on every create/update. Worst case with these values is ONE
# instance of 0.25 vCPU / 0.5 GB running the whole month (~USD 23 of compute).
# Never use --max-scale 0: in Code Engine it means "no limit", not "off".
CE_CAPS := --cpu 0.25 --memory 0.5G --min-scale 0 --max-scale 1 \
	--concurrency 10 --request-timeout 30

.PHONY: api-deploy
api-deploy: ## Build from source and deploy the tools API to Code Engine (capped)
	ibmcloud ce project select --name $(CE_PROJECT)
	if ibmcloud ce app get --name $(CE_APP) >/dev/null 2>&1; then \
		ibmcloud ce app update --name $(CE_APP) --build-source . --build-size small $(CE_CAPS) ; \
	else \
		ibmcloud ce app create --name $(CE_APP) --build-source . --build-size small --port 8080 \
			$(CE_CAPS) --env-from-secret $(CE_SECRET) ; \
	fi

.PHONY: api-off
api-off: ## Kill switch: take the API off the internet (no traffic = no charges); keeps everything
	ibmcloud ce project select --name $(CE_PROJECT)
	ibmcloud ce app update --name $(CE_APP) --visibility project --min-scale 0

.PHONY: api-on
api-on: ## Put the API back on its public URL (same URL, no rebuild)
	ibmcloud ce project select --name $(CE_PROJECT)
	ibmcloud ce app update --name $(CE_APP) --visibility public

.PHONY: api-status
api-status: ## Show visibility, scale caps and running instances of the tools API
	ibmcloud ce project select --name $(CE_PROJECT)
	ibmcloud ce app get --name $(CE_APP)

.PHONY: api-scale-demo
api-scale-demo: ## Keep one instance warm for a demo (~USD 0.75/day)
	ibmcloud ce app update --name $(CE_APP) --min-scale 1

.PHONY: api-scale-idle
api-scale-idle: ## Scale the tools API back to zero (free tier)
	ibmcloud ce app update --name $(CE_APP) --min-scale 0

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
