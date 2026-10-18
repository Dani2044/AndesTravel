# Operations Runbook

## 1. Local development

```bash
uv sync
docker compose up -d          # postgres+pgvector, langfuse, mailhog
make db-up && make seed
make run                      # FastAPI gateway on :8000
```

## 2. Services and ports

| Service | Port | Purpose |
|---|---|---|
| gateway (FastAPI) | 8000 | webhooks + API |
| postgres | 5432 | data + checkpointer + vector |
| langfuse | 3000 | traces, cost, evals |
| mailhog | 8025 | email/SMS capture |

## 3. Common tasks

| Task | Command |
|---|---|
| Migrate DB | `make db-migrate` |
| Seed catalog | `make seed` |
| Unit + integration | `make test` |
| Load test | `make test-load` |
| Adversarial test | `make test-adversarial` |
| Lint / format | `make lint` |
| Type-check | `make typecheck` |
| Pull LLM | `make ollama-pull` |

## 4. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` on 5432 | DB not up | `docker compose up -d postgres` |
| Agents return empty | Ollama not running | `ollama serve` and pull the model |
| WhatsApp webhook 403 | verify token mismatch | check `WHATSAPP_VERIFY_TOKEN` |
| Quote tool timeout | mock API down | restart `booking_api` |
| Slow first token | cold model | warm the model on startup |

## 5. Health checks

- `GET /health` — gateway liveness.
- `GET /health/deps` — DB, MCP server, LLM reachability.

## 6. Incident response

- Personal-data incident → follow the data-incident procedure in
  [`governance.md`](governance.md): contain, assess, notify, record in `audit_log`.
- Assistant outage → check `/health/deps`; degrade to alternate channels if a single
  channel is down.

## 7. Service levels (targets)

| Severity | Description | First response | Target resolution |
|---|---|---|---|
| Critical | assistant down | 30 min | 4 h |
| High | core function degraded | 2 h | 1 business day |
| Medium | secondary function | 1 business day | 3 business days |
| Low | question/improvement | 2 business days | per planning |

Target availability: **99.5%** monthly.
