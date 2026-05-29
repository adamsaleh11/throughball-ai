# Plan: ADK Runtime Foundation

> Source PRD: `docs/prds/06-04-adk-runtime-foundation.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no new HTTP route is required for this slice; the stable public surface is the ADK runtime package boundary.
- **Schema**: no database schema changes. Session state is in-memory and compact for this ticket.
- **Key models**: ADK runtime config, ADK model config, compact session state, normalized LLM metrics, callback telemetry hooks.
- **Auth**: no authentication or authorization changes.
- **External services**: Google ADK is the primary future agent framework, but runtime initialization and tests must not make live Gemini, Vertex, ADK server, MCP network, or external service calls.
- **Model policy**: Gemini Flash is the default and only enabled model path. Gemini Pro remains disabled by default.
- **Cost controls**: max output tokens, low factual temperature, max agent iterations, compact state, bounded counters, and compact telemetry are required.
- **Tool boundary**: MCP remains the only tool access boundary; ADK integration must not bypass MCP tracing, retry, degraded, latency, or budget behavior.

---

## Phase 1: ADK Package Skeleton and Local Runtime

**User stories**: 1, 2, 3, 25

### What to build

Create the ADK runtime package boundary and a local runtime factory that can be constructed from existing settings without contacting Gemini, Vertex, ADK servers, MCP network transport, or external services. The runtime should expose enough identity and configuration metadata for future agents to depend on it.

### Acceptance criteria

- [ ] The ADK package is importable through the throughball-ai namespace.
- [ ] Runtime construction succeeds locally with default settings.
- [ ] Runtime construction exposes service, environment, model, and iteration-limit metadata.
- [ ] Runtime construction does not require live Google credentials or external network calls.

---

## Phase 2: Flash-Only ADK Model Configuration

**User stories**: 4, 5, 6, 7, 8, 9, 10, 11, 26

### What to build

Adapt the existing environment-backed settings and deterministic model router into an ADK-ready model configuration surface. The config should preserve Gemini Flash as the default model, keep Gemini Pro disabled by default, expose max output tokens and temperature, and provide a bounded default max iteration setting with per-agent override support.

### Acceptance criteria

- [ ] ADK model config loads Gemini Flash from environment-backed settings.
- [ ] Gemini Pro is disabled by default and not selected by normal or escalated routes.
- [ ] Model config includes max output tokens and temperature.
- [ ] Runtime config includes a default max iteration limit.
- [ ] Per-agent max iteration overrides are supported without changing global settings.
- [ ] Model routing remains side-effect free and does not make model calls.

---

## Phase 3: Compact Session State Service

**User stories**: 12, 13, 14, 15, 27

### What to build

Add an in-memory ADK session service that stores compact task state for a request or agent run. It should store IDs, selected model, compact task state, retrieval references, short summaries, iteration count, tool-call count, retry count, and degraded status while avoiding full retrieved documents, full prompts, full completions, or runaway state growth.

### Acceptance criteria

- [ ] A session can be created and retrieved by ID.
- [ ] Session state stores compact task state and short summaries.
- [ ] Session state stores retrieval references without storing full document text.
- [ ] Session state tracks iteration, tool-call, retry, selected-model, and degraded fields.
- [ ] State helpers prevent large document-like payloads from being stored by default.
- [ ] Session service remains in-memory for this ticket.

---

## Phase 4: LLM Metrics Normalization

**User stories**: 21, 22, 23, 24, 29

### What to build

Add a normalized LLM metrics payload that converts provider usage and runtime counters into compact operational fields. The metrics should tolerate missing provider usage metadata and calculate tokens per second and cost per request with safe defaults.

### Acceptance criteria

- [ ] Metrics include prompt tokens, completion tokens, total tokens, latency, and model name.
- [ ] Metrics include tokens per second with zero-safe behavior.
- [ ] Metrics include estimated cost and cost per request.
- [ ] Metrics include tool call count, retry count, and degraded status.
- [ ] Missing provider usage metadata results in safe zero/default fields.
- [ ] Cost estimation reuses the existing cost helper.

---

## Phase 5: Callback Tracing Hooks

**User stories**: 16, 17, 18, 19, 20, 28

### What to build

Add compact callback hooks for agent, model, and tool lifecycle events. The hooks should produce structured telemetry aligned with existing observability vocabulary and avoid storing or logging full prompts, completions, retrieved documents, secrets, or private user data.

### Acceptance criteria

- [ ] Agent lifecycle callback emits a compact structured event.
- [ ] Model lifecycle callback emits token, latency, cost, retry, degraded, and model fields.
- [ ] Tool lifecycle callback emits compact status, latency, retry, degraded, and tool-count fields.
- [ ] Callback telemetry includes stable request, trace, span, agent, and tool identifiers where provided.
- [ ] Callback telemetry avoids full prompt text, completion text, full retrieved documents, secrets, and private user data.

---

## Phase 6: Foundation Acceptance Coverage

**User stories**: 1-30

### What to build

Close the foundation with behavior-level coverage across runtime construction, Flash-only model configuration, compact session state, metrics, and callback telemetry. Tests should assert public contracts and local initialization behavior rather than ADK internals.

### Acceptance criteria

- [ ] ADK runtime initialization tests pass without live external services.
- [ ] Flash-only model configuration tests pass and Gemini Pro remains disabled by default.
- [ ] Compact session-state tests verify summaries, retrieval references, counters, and large-payload rejection.
- [ ] Metrics tests verify derived fields and safe defaults.
- [ ] Callback tests verify compact structured telemetry shape.
- [ ] The relevant test suite passes without live Gemini, Vertex, ADK server, MCP network transport, hosted telemetry, or external API calls.
