# Data Model

PostgreSQL 16 with the `pgvector` extension. All personal data is governed by
consent-by-purpose, data minimization and encryption (see [`governance.md`](governance.md)).

## 1. Entities

### traveler
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | surrogate identifier |
| external_ref | text | optional CRM reference |
| created_at | timestamptz | |

### profile
| Column | Type | Notes |
|---|---|---|
| traveler_id | uuid FK → traveler | |
| attributes | jsonb | minimized profile (destinations, party, preferences) |
| updated_at | timestamptz | |

### consent
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| traveler_id | uuid FK → traveler | |
| purpose | enum | `personalization` \| `quotation` \| `booking` |
| granted | boolean | |
| granted_at | timestamptz | |
| revoked_at | timestamptz | null while active |
| evidence | jsonb | versioned proof (channel, text version, ts) |

One row per (traveler, purpose) lifecycle event. The active consent is the latest
non-revoked row for a purpose.

### memory
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| traveler_id | uuid FK → traveler | |
| kind | enum | `fact` \| `preference` \| `event` |
| content | text | |
| embedding | vector(1024) | bge-m3 |
| channel | enum | origin channel |
| ts | timestamptz | |

### audit_log (append-only)
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| actor | text | traveler id, agent id or system |
| action | text | e.g. `consent.grant`, `quote.create`, `reservation.create` |
| entity | text | target entity |
| payload_redacted | jsonb | PII-redacted snapshot |
| ts | timestamptz | |

### destination / package / rate
Catalog tables backing the RAG knowledge base and the quotation agent.

| Table | Columns |
|---|---|
| destination | id, name, region, tags jsonb |
| package | id, destination_id, name, description, duration_days, tags jsonb |
| rate | id, package_id, valid_from, valid_to, currency, amount, supplier |

### reservation
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| traveler_id | uuid FK → traveler | |
| quote_id | uuid FK → quote | |
| status | enum | `pending` \| `confirmed` \| `cancelled` |
| totals | jsonb | amount, currency, commission |
| idempotency_key | text unique | prevents duplicate bookings |
| created_at | timestamptz | |

### quote
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| traveler_id | uuid FK → traveler | |
| package_id | uuid FK → package | |
| lines | jsonb | itemized amounts |
| total | jsonb | amount, currency |
| expires_at | timestamptz | explicit validity |

## 2. LangGraph persistence

- **Checkpointer** (`PostgresSaver`): conversational state, keyed by `thread_id = traveler_id`.
- **Store**: long-term memory records, keyed by `traveler_id`.

These tables are managed by LangGraph's own migrations; the domain tables above are
managed by the project's Alembic migrations.

## 3. Consent policy

- **Purpose-bound**: data is only used for a purpose the traveler has authorized.
- **Minimized**: only attributes required for a purpose are stored.
- **Auditable**: every grant/revoke is written to `consent` with versioned evidence.
- **ARCO**: traveler can access, rectify, cancel and oppose; operations are recorded in
  `audit_log`.
- **Encryption**: at rest (column/disk) and in transit (TLS).

Right-to-erasure removes the traveler's rows across `profile`, `memory` and cascades;
`audit_log` keeps a redacted, non-identifying record of the erasure itself.
