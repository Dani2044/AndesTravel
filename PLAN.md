# AndesTravel — Engineering Plan (TDD · open source · LangGraph)

Implementation plan for the **Andes Travel traveler-attention assistant**: an omnichannel
conversational assistant with persistent memory, built entirely on **open-source,
free, local-first tooling** and orchestrated with **LangGraph**.

This document is the working build plan. It defines the stack, the architecture, the test
plan (unit / integration / load / adversarial), the implementation order, and the
human-integration boilerplate map. Product and reference documentation lives under
[`docs/`](docs/).

---

## 1. Goal

Build a production-grade reference implementation of a multichannel travel assistant that:

- unifies voice, web, WhatsApp and email/SMS into a single conversation thread;
- keeps a persistent traveler profile and memory **across channels**;
- runs four specialized agents (profiling, recommendation, quotation, reservations)
  under a supervisor;
- integrates business systems through a single stable **MCP** contract;
- quotes in **under 5 minutes** and can create reservations from the conversation;
- handles human handoff with full context;
- embeds governance from day one: consent (Ley 1581), OWASP LLM Top 10 controls,
  evaluation and observability.

Everything runs locally and for free. External providers (WhatsApp, telephony, payments)
are integrated through adapters with working mocks so the full test suite runs offline.

---

## 2. Locked decisions

| Area | Decision |
|---|---|
| Orchestration | LangGraph (supervisor + 4 subagents) + LangChain |
| LLM | Ollama local, default **`qwen2.5:14b`** (env-configurable) |
| Embeddings | `BAAI/bge-m3` via `sentence-transformers` (local) |
| Persistence | PostgreSQL 16 + pgvector; LangGraph checkpointer + Store |
| Integration | MCP Python SDK (typed tools, stdio + SSE) |
| WhatsApp | Meta WhatsApp Cloud API (test number) |
| Voice | Twilio Programmable Voice + faster-whisper (STT) + Piper (TTS) |
| Payments | Wompi sandbox |
| Observability | Langfuse self-hosted + OpenTelemetry |
| Evals / red team | RAGAS / promptfoo |
| Load | Locust |
| Tests | pytest + pytest-asyncio + respx + testcontainers |
| CI | GitHub Actions |
| Language | English (code, tests, docs) |
| Python | `>=3.12`; Docker/CI pinned to **3.12** |

### 2.1 Python version

The LangGraph/LangChain ecosystem is validated on **Python 3.12**. Newer interpreters
(3.14/3.15) may not have wheels for every dependency yet. `requires-python = ">=3.12"`,
Docker and CI pinned to **3.12**. Newer local interpreters are supported only if the
full dependency set installs cleanly.

---

## 3. Repository structure (single uv package, `src/andes`)

```text
AndesTravel/
├── README.md  LICENSE  pyproject.toml  Makefile  .env.example
├── docker-compose.yml            # postgres+pgvector, langfuse, mailhog
├── .github/workflows/ci.yml
├── docs/
│   ├── architecture.md           # layers, agents, flows
│   ├── data-model.md             # schema + consent policy
│   ├── mcp-contract.md           # MCP tool contract
│   ├── governance.md             # Ley 1581, OWASP LLM, evaluation
│   ├── integration.md            # human boilerplate / TODO(human) checklist
│   ├── runbook.md                # operations
│   └── test-plan.md              # the four test suites + gates
├── src/andes/
│   ├── core/          # domain models, schemas, config, enums, seed, vector
│   ├── memory/        # profile + long-term memory + consent
│   ├── knowledge/     # RAG ingest + retriever (pgvector, bge-m3)
│   ├── agents/        # LangGraph supervisor + per-intent handlers
│   ├── mcp_server/    # tools: check_availability / quote_package / create_reservation
│   ├── booking_api/   # mock external business systems (FastAPI)
│   ├── channels/      # adapters: web, whatsapp, voice, email + mocks
│   ├── governance/    # OWASP guards, PII redaction, audit trail
│   ├── observability/ # Langfuse + OTel wiring
│   ├── analytics/     # AgentOps metrics + indicators
│   ├── persistence/   # SQLAlchemy 2.0 + pgvector models + async repositories
│   ├── conversation.py# channel-agnostic orchestration service (L2 entry point)
│   ├── wiring.py      # dependency container
│   ├── cli.py         # migrate / seed / info
│   └── apps/api/      # FastAPI gateway (webhook entrypoints)
├── evals/             # RAG evaluation (ragas; offline retrieval accuracy in CI)
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── load/          # locust
│   └── adversarial/   # promptfoo configs
└── scripts/           # pgvector init
```

---

## 4. Architecture (5 layers + governance)

| Layer | Responsibility | Components |
|---|---|---|
| L1 Experience | Traveler interaction in any channel | voice (STT/TTS), web, WhatsApp, SMS/email, human handoff |
| L2 Orchestration | Agent coordination and conversation flow | LangGraph supervisor + profiling, recommendation, quotation, reservations subgraphs |
| L3 Knowledge & context | What the system knows and remembers | RAG knowledge bases, profile + omnichannel memory |
| L4 Business integration | Action on transactional systems | MCP server + availability/quote/reservation tools |
| L5 Persistent data | Durable, auditable storage | profile+memory, catalog+rates, reservations, audit log |
| Governance (cross-cutting) | Trust, compliance, improvement | agent evaluation, observability, consent, encryption |

### 4.1 Agents

| Agent | Function |
|---|---|
| Orchestrator | Route, keep the multi-turn thread, transfer between agents, handoff |
| Profiling | Build and update the traveler profile + memory |
| Recommendation | Semantic match between profile and inventory (RAG) |
| Quotation | Check availability and issue a quote with explicit expiry |
| Reservations | Create the reservation and persist context |

Full detail: [`docs/architecture.md`](docs/architecture.md).

---

## 5. Data model (with consent)

`traveler`, `profile`, `consent` (per purpose: personalization, quotation, booking),
`memory` (with embeddings), `audit_log`, `destination`, `package`, `rate`, `reservation`.
Full detail: [`docs/data-model.md`](docs/data-model.md).

Compliance: consent-by-purpose, data minimization, ARCO rights, encryption in transit and
at rest (Ley 1581 / Decreto 1377), CONPES 4144 principles, OWASP LLM Top 10 controls.

---

## 6. Implementation order (TDD)

Every work item: write failing tests first, then minimal implementation, then refactor.
Never merge red. Each step must pass unit + integration + lint (ruff) + type-check (mypy).

| Phase | Initiatives | Deliverable | Gate |
|---|---|---|---|
| 1 Foundation | I1, I2, I9 | blueprint, data model, profile+consent, governance framework | consent traceable e2e |
| 2 Agent core | I3, I5, I10 | knowledge base + RAG, supervisor + profiling/recommendation agents, observability | 3 flows live; top-3 > 0.85 |
| 3 Transaction | I4, I6, I7 | web + WhatsApp channels with memory, MCP server + tools, quotation + booking | cross-channel continuity; quote < 5 min; booking created |
| 4 Scale | I8, I11, I12 | voice channel, analytics dashboard, post-sales + payments | voice intent > 90%; indicators; booking + payment |

Cross-cutting: `docs/integration.md`, `docs/runbook.md`, seed data, CI.

---

## 7. Test plan (summary)

Full detail in [`docs/test-plan.md`](docs/test-plan.md).

- **Unit** — schemas, consent/minimization/ARCO, profile merge, retriever ranking,
  agent routing, grounded quotation, reservation idempotency, MCP schemas, channel
  normalization, PII redaction, OWASP guards.
- **Integration** — end-to-end message→…→response, cross-channel continuity, reservation
  via MCP, handoff, RAG e2e, LangGraph↔MCP binding, consent evidence, observability.
- **Load** (Locust) — 30k contacts/month concurrency, p95 latency, quote < 5 min,
  tool availability ≥ 99.5%, cost/conversation < USD 0.15, soak.
- **Adversarial** (promptfoo) — injection (direct + indirect), jailbreak, forced
  hallucination, cross-traveler PII exfiltration, consent bypass, tool abuse/replay, DoS.

---

## 8. Non-functional targets

- Availability **99.5%** monthly.
- First response in **seconds**; quote in **< 5 min**.
- **30,000 contacts/month** with headroom.
- Cost per conversation **< USD 0.15**.
- OWASP LLM Top 10 addressed; auditable consent; encryption in transit and at rest; RBAC.

---

## 9. Human-integration boilerplate (`TODO(human)`)

External accounts/credentials required for production. The codebase ships `TODO(human):`
markers plus working mocks so the suite passes offline. Steps in
[`docs/integration.md`](docs/integration.md).

| Item | Human action | Mock provided |
|---|---|---|
| WhatsApp | Meta Business app + test number verification + webhook verify token | in-process fake webhook |
| Voice | Twilio SID/token + phone number | audio fixture pipeline |
| Payments | Wompi sandbox keys | deterministic fake charge |
| Ollama | Install + `ollama pull qwen2.5:14b` | scripted fake LLM for unit tests |
| Secrets | Production secret manager, TLS termination | `.env.example` + local defaults |
