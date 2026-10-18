# Governance, Compliance and AI Safety

Governance is a cross-cutting band, not a final phase. It covers consent and privacy,
model-safety controls, evaluation, observability and the audit trail.

## 1. Privacy and consent (Ley 1581 / Decreto 1377)

- **Consent by purpose**: `personalization`, `quotation`, `booking`. Data is only used for
  an authorized purpose.
- **Data minimization**: only the attributes a purpose needs are stored.
- **ARCO rights**: access, rectification, cancellation and opposition are implemented as
  first-class operations, each recorded in `audit_log`.
- **Evidence**: every grant/revoke is stored with versioned evidence (channel, text
  version, timestamp) to produce proof on demand.
- **Encryption**: in transit (TLS) and at rest (column/disk).
- **Retention**: configurable per data type; erasure cascades across personal tables.

## 2. Model-safety controls (OWASP LLM Top 10)

| Risk | Control |
|---|---|
| LLM01 Prompt injection | input/output guards; tool outputs treated as untrusted data, never as instructions |
| LLM02 Insecure output handling | structured outputs only; no raw model text is executed |
| LLM03 Training-data poisoning | knowledge base is curated and versioned; ingestion is authenticated |
| LLM04 Model DoS | bounded iterations, input length limits, rate limiting |
| LLM05 Supply-chain | pinned dependencies, lockfile, SBOM |
| LLM06 Sensitive-information disclosure | PII redaction in logs; per-traveler data isolation |
| LLM07 Insecure plugin design | typed MCP tools, strict schemas, least privilege |
| LLM08 Excessive agency | tools are read-mostly; writes require explicit, consented user intent |
| LLM09 Overreliance | grounded answers only; figures must come from tools; expiry shown |
| LLM10 Model theft | local model; no external exposure of weights |

## 3. Anti-hallucination

- Quotation and reservation facts come **only** from MCP tool responses.
- The agent layer validates that any price/availability it presents exists in the tool
  output; otherwise it re-queries or escalates.
- Quotes carry an explicit `expires_at`; expired data is never presented as current.

## 4. Human handoff

- Sensitive or low-confidence cases escalate to a human advisor.
- The advisor receives a **structured summary**: profile, intent, memory highlights,
  current quote and open questions.
- The handoff is a first-class contract, covered by integration tests.

## 5. Evaluation

- **RAGAS** for retrieval/answer quality (recommendation top-3 accuracy > 0.85).
- **promptfoo** for adversarial suites mapped to OWASP LLM Top 10.
- Regression thresholds run in CI; load and adversarial suites run nightly and before
  each phase gate.

## 6. Observability and audit

- **Langfuse** records traces, token usage and cost per conversation.
- **OpenTelemetry** exports traces/metrics to the ops backend.
- **audit_log** is append-only: consent, quote, reservation and handoff events with
  redacted payloads.

## 7. Alignment with CONPES 4144 principles

Transparency, purpose limitation and human oversight are enforced by the design:
documented agent behavior, purpose-bound data, and mandatory handoff for sensitive cases.
