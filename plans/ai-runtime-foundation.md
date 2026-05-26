# Plan: AI Runtime Foundation

> Source PRD: docs/prds/ai-runtime-foundation.md

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: expose `GET /health` for local service readiness. No model execution route is part of this foundation.
- **Schema**: no database schema changes.
- **Key models**: typed runtime settings, deterministic model route metadata, and contract-aligned telemetry event payloads.
- **Auth**: no authentication or authorization in this ticket.
- **External services**: Vertex AI, Google ADK, MCP SDK, and OpenTelemetry are dependency boundaries only; startup and health checks do not make live external calls.
- **Model policy**: default and escalation model routes both resolve to Gemini Flash.
- **Telemetry policy**: structured JSON logs are the default sink; no hosted telemetry exporter is required.

---

## Phase 1: Local Runtime Skeleton

**User stories**: 1, 2, 3, 20

### What to build

Create a local Python HTTP service that can start with uvicorn and expose a health endpoint. The endpoint should confirm service status and runtime identity while avoiding live provider calls and secret exposure.

### Acceptance criteria

- [ ] The AI service starts locally through the documented uvicorn command.
- [ ] `GET /health` returns an HTTP 200 response.
- [ ] The health payload includes status, service, environment, default model, and Vertex readiness.
- [ ] The health payload does not expose credentials or secrets.
- [ ] The health endpoint does not call Vertex AI.

---

## Phase 2: Typed Configuration and Vertex Readiness

**User stories**: 4, 5, 20

### What to build

Add dotenv-backed typed runtime configuration for local development and future deploy environments. Vertex readiness should be derived from configuration presence and enabled state, not from a live API probe.

### Acceptance criteria

- [ ] Runtime settings load from environment variables and `.env`.
- [ ] Missing Vertex project or location marks Vertex as not configured.
- [ ] Vertex readiness never requires real Google credentials.
- [ ] Defaults preserve local-first development.

---

## Phase 3: Flash-Only Model Routing

**User stories**: 6, 7, 8, 9, 10, 22

### What to build

Add deterministic model routing that resolves route metadata for future agents. The router should enforce Gemini Flash as the default and escalation model, apply configured output caps, and keep factual temperature low.

### Acceptance criteria

- [ ] The default model route resolves to Gemini Flash.
- [ ] The escalation route also resolves to Gemini Flash.
- [ ] Route metadata includes max output token cap and temperature.
- [ ] Routing does not make model calls.
- [ ] The design keeps deterministic ranking, filtering, scoring, and itinerary sequencing out of AI prompts.

---

## Phase 4: Structured Telemetry and Cost Helpers

**User stories**: 11, 12, 13, 14, 15, 21

### What to build

Add structured telemetry helpers for future model calls. Events should align with the observability contract, include token and cost fields, tolerate missing provider usage metadata, and write compact JSON logs locally.

### Acceptance criteria

- [ ] Model-call telemetry includes estimated cost.
- [ ] Model-call telemetry includes prompt, completion, and total token fields.
- [ ] Missing provider usage metadata results in safe zero/default values.
- [ ] Telemetry avoids full prompts, completions, documents, secrets, and private user data.
- [ ] OpenTelemetry remains an available local boundary without requiring a remote exporter.

---

## Phase 5: AI Runtime Module Boundaries

**User stories**: 16, 17, 18, 22

### What to build

Create stable package boundaries for orchestration, agents, MCP, evals, telemetry, and routing. These boundaries should make later tickets straightforward while avoiding live tools, model execution, loops, or recursion.

### Acceptance criteria

- [ ] Orchestrator, agent, MCP, eval, telemetry, and model router modules are importable.
- [ ] MCP modules do not implement live external tools yet.
- [ ] Agent modules do not run automatic multi-agent loops.
- [ ] Eval modules do not run automatic eval loops.

---

## Phase 6: Foundation Test Coverage and Developer Docs

**User stories**: 19 plus verification for 1-18

### What to build

Add focused tests for externally visible behavior and update local developer documentation. Tests should cover config loading, health behavior, model routing, telemetry event shape, and importable runtime boundaries.

### Acceptance criteria

- [ ] Tests verify health behavior through the HTTP interface.
- [ ] Tests verify config-driven Vertex readiness without credentials.
- [ ] Tests verify Flash-only routing.
- [ ] Tests verify telemetry event shape.
- [ ] Tests avoid live Vertex AI, Gemini, MCP, or external network calls.
- [ ] README documents local setup, startup, health check, and test commands.
