# Test Plan

Four suites. Unit and integration run on every change; load and adversarial run nightly
and before each phase gate.

## 1. Unit (`tests/unit`, no network, mocked)

| Area | Cases | Acceptance |
|---|---|---|
| core | envelope/schema validation, env config | invalid payloads rejected |
| memory | grant/revoke per purpose, minimization, ARCO, profile merge, cross-channel retrieval, encryption | consent enforced; erasure cascades |
| knowledge | chunking, metadata filters, ranking | top-3 accuracy ≥ 0.85 on fixture |
| agents | intent→agent routing, supervisor transitions, state contracts, fallback, bounded iterations | no loops; deterministic routing |
| quotation | grounded on `quote_package` only, expiry, COP/IVA/commission math | zero hallucinated figures |
| reservations | validation, idempotency key, replay | duplicate replay returns same reservation |
| mcp_server | JSON Schema per tool, error/timeout/retry, auth | malformed calls rejected |
| channels | inbound→envelope normalization, webhook HMAC | signature mismatch rejected |
| governance | PII redaction, consent enforcement, OWASP in/out guards | secrets never logged |

## 2. Integration (`tests/integration`, real Postgres+pgvector + MCP via testcontainers)

| Case | Acceptance |
|---|---|
| message → profile → recommendation → quotation → response | completes end-to-end |
| cross-channel continuity (WhatsApp → web, days later) | memory + quote state recovered |
| reservation via MCP | persisted and confirmed |
| handoff with structured summary | advisor receives full context |
| RAG end-to-end (real vector store) | relevant packages returned |
| LangGraph ↔ MCP binding (stdio and SSE) | both transports work |
| consent evidence end-to-end | traceable proof emitted |
| controlled degradation | alternate channel used when one is down |
| observability | Langfuse receives traces; token/cost captured |

## 3. Load (`tests/load`, Locust)

| Scenario | Target |
|---|---|
| 30,000 contacts/month baseline → peak concurrency | no errors |
| p95 first response | seconds |
| quotation latency | < 5 min |
| checkpointer/store under concurrency | no corruption |
| tool availability | ≥ 99.5% |
| cost per conversation | < USD 0.15 |
| soak test | no leaks |

## 4. Adversarial (`tests/adversarial`, promptfoo; OWASP LLM Top 10)

| Case | Expectation |
|---|---|
| direct + indirect prompt injection (via RAG/tool output) | instructions ignored |
| jailbreak / system-prompt leak | refused |
| forced price/availability hallucination | grounded or escalated |
| cross-traveler PII exfiltration | denied |
| consent bypass | denied |
| tool abuse / `create_reservation` without quote or consent | denied |
| replay against idempotency | same result, no duplicate |
| DoS: long input, unicode/emoji flood, loop inducement | bounded, no crash |
| language-switch / obfuscation evasion | guards still hold |

## 5. Gate mapping

| Gate | Phases | Must pass |
|---|---|---|
| Gate 1 | I1, I2, I9 | unit + integration; consent traceable e2e |
| Gate 2 | I3, I5, I10 | + top-3 accuracy > 0.85; traces/alerts live |
| Gate 3 | I4, I6, I7 | + cross-channel continuity; quote < 5 min; tool availability ≥ 99.5% |
| Gate 4 | I8, I11, I12 | + voice intent > 90%; section-2.3 indicators; booking + payment |

## 6. Non-functional acceptance

- Availability 99.5% monthly.
- First response in seconds; quote < 5 min.
- 30,000 contacts/month with headroom.
- Cost per conversation < USD 0.15.
- OWASP LLM Top 10 addressed; auditable consent; encryption in transit and at rest; RBAC.
