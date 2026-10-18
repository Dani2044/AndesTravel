# MCP Contract

The MCP server is the **single integration boundary** between the agents (L2) and the
business systems (L4). It exposes typed, stateless, auditable tools over stdio and SSE.
A local mock implementation (`src/andes/booking_api`) backs the server so the whole system
runs and tests offline.

## Transport

| Mode | Use |
|---|---|
| stdio | local agents / CLI |
| SSE | network agents / integration tests |

## Common conventions

- **Strict JSON Schema** per tool; unknown fields are rejected.
- **Structured errors**: `{ "error": { "code", "message", "retryable" } }`.
- **Timeouts** on every call; **retries** only when `retryable = true`.
- **Auth**: bearer token from environment; never logged.
- **Idempotency**: write tools require an `idempotency_key`.
- **Audit**: every call is recorded in `audit_log` with a redacted payload.

---

## Tool: `check_availability`

Returns availability and the current rate for a package on given dates.

**Request**
```json
{
  "package_id": "uuid",
  "start_date": "2026-12-10",
  "end_date": "2026-12-17",
  "travelers": 4
}
```

**Response**
```json
{
  "available": true,
  "rate": { "amount": 5200000, "currency": "COP" },
  "supplier": "andes-supplier-01",
  "fetched_at": "2026-10-16T12:00:00Z"
}
```

Errors: `not_found`, `invalid_dates`, `upstream_unavailable` (retryable).

---

## Tool: `quote_package`

Produces a structured, itemized quote with an explicit expiry. The quotation agent must
present only what this tool returns.

**Request**
```json
{
  "package_id": "uuid",
  "travelers": 4,
  "start_date": "2026-12-10",
  "end_date": "2026-12-17",
  "options": { "include_insurance": true }
}
```

**Response**
```json
{
  "quote_id": "uuid",
  "lines": [
    { "description": "Base package", "amount": 5200000 },
    { "description": "Insurance",     "amount": 180000 }
  ],
  "total": { "amount": 5380000, "currency": "COP" },
  "expires_at": "2026-10-16T13:00:00Z"
}
```

Errors: `not_available`, `invalid_dates`, `upstream_unavailable` (retryable).

---

## Tool: `create_reservation`

Creates a reservation from an accepted, non-expired quote.

**Request**
```json
{
  "quote_id": "uuid",
  "traveler_id": "uuid",
  "idempotency_key": "uuid",
  "payment": { "provider": "wompi", "reference": "…" }
}
```

**Response**
```json
{
  "reservation_id": "uuid",
  "status": "confirmed",
  "totals": { "amount": 5380000, "currency": "COP", "commission": 645600 }
}
```

Errors: `quote_expired`, `already_exists` (idempotent replay), `payment_failed`,
`consent_required`, `upstream_unavailable` (retryable).

---

## Guarantees

- **Anchoring**: quotation and booking data come only from tool responses (no model
  invention). The agent layer rejects any figure not present in the tool result.
- **Availability**: target ≥ 99.5% tool availability (measured by the load suite).
- **Portability**: because the contract is MCP, the backing systems can be replaced
  without changing the agents.
