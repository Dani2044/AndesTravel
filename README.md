# AndesTravel

**An omnichannel travel-assistant reference implementation with persistent memory, built
on open-source agents (LangGraph).**

AndesTravel unifies voice, web, WhatsApp and email/SMS into a single conversation thread.
A supervisor orchestrates four specialized agents — profiling, recommendation, quotation
and reservations — over knowledge bases and a persistent traveler profile. Business
systems are reached through a single **MCP** contract. The assistant quotes in under five
minutes and can create a reservation without leaving the conversation, escalating to a
human advisor with full context when needed.

Everything runs **locally and for free**: a local LLM (Ollama), local embeddings,
PostgreSQL + pgvector, and open-source observability. External providers (WhatsApp,
telephony, payments) are wrapped by adapters with working mocks, so the entire test suite
runs offline.

---

## Highlights

- **Memory as infrastructure** — profile and conversation memory persist across channels.
- **Four specialized agents** under a LangGraph supervisor, sharing one state object.
- **Single integration boundary** — an MCP server exposing typed, auditable tools.
- **Governance from day one** — consent by purpose, OWASP LLM Top 10 controls, audit trail.
- **Open source and local-first** — no paid platform, no proprietary SDKs.

## Architecture at a glance

```
L1 Experience     voice · web · WhatsApp · email/SMS · human handoff
L2 Orchestration  LangGraph supervisor → profiling · recommendation · quotation · reservations
L3 Knowledge      RAG knowledge bases · profile + omnichannel memory
L4 Integration    MCP server → check_availability · quote_package · create_reservation
L5 Data           profile+memory · catalog+rates · reservations · audit log
Governance        evaluation · observability · consent · encryption
```

See [`docs/architecture.md`](docs/architecture.md) for the full design.

## Stack

| Concern | Choice |
|---|---|
| Agents | LangGraph + LangChain |
| LLM | Ollama (`qwen2.5:14b` by default) |
| Embeddings | `BAAI/bge-m3` (local) |
| Data | PostgreSQL 16 + pgvector |
| Integration | MCP Python SDK |
| API | FastAPI |
| Observability | Langfuse + OpenTelemetry |
| Tests | pytest, testcontainers, Locust, promptfoo |

## Repository layout

```
src/andes/  core · memory · knowledge · agents · mcp_server · booking_api · channels
            governance · observability · analytics · persistence · apps/api
evals/      RAG evaluation (ragas; offline retrieval accuracy in CI)
tests/      unit · integration · load · adversarial
docs/       architecture · data-model · mcp-contract · governance · integration · runbook · test-plan
```

## Quickstart

```bash
# 0. prerequisites: Python 3.12, uv, Docker, Ollama
brew install ollama && ollama serve &      # if not already running
ollama pull qwen2.5:14b

# 1. install
uv sync

# 2. local infrastructure (postgres+pgvector, langfuse, mailhog)
docker compose up -d

# 3. database + seed data
make db-up && make seed

# 4. run the test suites
make test            # unit + integration
make test-load       # Locust scenarios
make test-adversarial # promptfoo red-team

# 5. run the gateway
make run
```

Environment variables are documented in [`.env.example`](.env.example).

## Documentation

| Document | Contents |
|---|---|
| [`PLAN.md`](PLAN.md) | Engineering plan, decisions, implementation order |
| [`docs/architecture.md`](docs/architecture.md) | Layers, agents, sequence and data-flow |
| [`docs/data-model.md`](docs/data-model.md) | Schema and consent policy |
| [`docs/mcp-contract.md`](docs/mcp-contract.md) | MCP tool contract |
| [`docs/governance.md`](docs/governance.md) | Compliance and AI governance |
| [`docs/integration.md`](docs/integration.md) | Production integration checklist |
| [`docs/runbook.md`](docs/runbook.md) | Operations |
| [`docs/test-plan.md`](docs/test-plan.md) | Test strategy and gates |

## License

Apache License 2.0 — see [LICENSE](LICENSE).
