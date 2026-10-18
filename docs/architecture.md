# Architecture

AndesTravel is organized in **five layers** plus a cross-cutting **governance** band. The
design keeps a single conversation thread per traveler and a single integration boundary
to the business systems.

## 1. Layers

| Layer | Responsibility | Components |
|---|---|---|
| **L1 Experience** | Traveler interaction in any channel | voice (STT/TTS), web, WhatsApp, SMS/email, human handoff |
| **L2 Orchestration** | Agent coordination and conversation flow | LangGraph supervisor + profiling, recommendation, quotation, reservations subgraphs |
| **L3 Knowledge & context** | What the system knows and remembers | RAG knowledge bases (catalog/destinations, policies/FAQs), profile + omnichannel memory |
| **L4 Business integration** | Action on transactional systems | MCP server + `check_availability`, `quote_package`, `create_reservation` |
| **L5 Persistent data** | Durable, auditable storage | profile+memory, catalog+rates, reservations, audit log |
| **Governance** | Trust, compliance, improvement | agent evaluation, observability, consent, encryption |

```
        ┌──────────────────────────── L1 Experience ────────────────────────────┐
        │  voice (STT/TTS)   web   WhatsApp   email/SMS        human handoff    │
        └───────────────────────────────────┬──────────────────────────────────┘
                                             │ canonical message envelope
        ┌───────────────────────────────────▼──────────────────────────────────┐
        │  L2 Orchestration — LangGraph supervisor                              │
        │  ┌────────────┬───────────────┬───────────┬──────────────┐            │
        │  │ profiling  │ recommendation│ quotation │ reservations │            │
        │  └────────────┴───────────────┴───────────┴──────────────┘            │
        └───────┬───────────────────┬────────────────────┬──────────────────────┘
                │                   │                    │
        ┌───────▼────────┐  ┌───────▼────────┐  ┌────────▼─────────┐
        │ L3 Knowledge   │  │ L4 Integration │  │ L5 Data          │
        │ RAG + memory   │  │ MCP server     │  │ profile, catalog,│
        │ (pgvector)     │  │ (typed tools)  │  │ reservations     │
        └───────┬────────┘  └───────┬────────┘  └────────┬─────────┘
                │                   │                    │
        ┌───────▼───────────────────▼────────────────────▼─────────┐
        │ Governance — evaluation · observability · consent · audit │
        └──────────────────────────────────────────────────────────┘
```

## 2. Canonical message envelope

Every channel adapter normalizes inbound traffic into a single envelope before it reaches
L2:

```json
{
  "traveler_id": "uuid",
  "channel": "whatsapp | web | voice | email | sms",
  "session_id": "uuid",
  "text": "…",
  "attachments": [],
  "locale": "es-CO",
  "received_at": "RFC3339",
  "raw": { }
}
```

This indirection keeps the agents channel-agnostic and makes cross-channel continuity a
property of the state, not of the channel.

## 3. Agents (L2)

A **supervisor** graph routes each turn to one of four subgraphs, then merges the result
back into the shared state.

| Agent | Responsibility | Reads | Writes |
|---|---|---|---|
| Orchestrator | classify intent, route, keep the thread, decide handoff | state | routing decision |
| Profiling | build and update profile + memory | envelope, memory store | profile, memory |
| Recommendation | semantic match profile ↔ inventory | profile, RAG | candidate packages |
| Quotation | availability + price, issue quote with expiry | package, MCP | quote |
| Reservations | create and persist the reservation | accepted quote, MCP | reservation |

### Shared state

```
TravelerState {
  messages, traveler_id, channel, profile, memory,
  consent, intent, quote, reservation, handoff
}
```

- **Checkpointer** (`PostgresSaver`): one thread per traveler → cross-channel continuity.
- **Store**: long-term profile and preferences that outlive a session.
- **Safety**: bounded `max_iterations`; deterministic fallback and handoff transitions.

## 4. Cross-channel continuity

```
traveler ── WhatsApp ──► gateway ──► checkpointer(thread=traveler_id)
   … days later …
traveler ── web ───────► gateway ──► same thread → profile + memory recovered
```

When a traveler resumes on another channel, the supervisor loads the same thread, so the
profile, preferences, quote state and history are available without re-asking.

## 5. Reservation flow

| Step | Action | Layer |
|---|---|---|
| 1 | Traveler expresses a request on any channel | L1 |
| 2 | Profile, preferences and memory are retrieved | L3 + agent |
| 3 | Supervisor delegates to recommendation or quotation | L2 |
| 4 | Availability is checked and a quote is issued | L4 |
| 5 | Traveler accepts; `create_reservation` is called via MCP | L4 |
| 6 | Reservation is persisted and context is stored | L5 |
| — | On escalation, the advisor receives a structured summary | Handoff |

## 6. Data-flow processes

`P1` channel ingest/normalization · `P2` profile & memory · `P3` agent orchestration ·
`P4` recommendation/personalization · `P5` quotation/availability · `P6` reservation ·
`P7` handoff · `P8` security/governance/observability.

Stores: `S1` profile+memory · `S2` catalog+rates · `S3` reservations · `S4` conversation/agent log.

## 7. Integration contract

The MCP server is the only path from agents to business systems. Its tools are typed,
auditable and stateless; the systems behind it can change without touching the agents,
and the agents can evolve without touching the systems. See
[`mcp-contract.md`](mcp-contract.md).
