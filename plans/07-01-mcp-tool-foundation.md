# Plan: MCP Tool Foundation

> Source PRD: docs/prds/07-01-mcp-tool-foundation.md

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no new product HTTP route is required; the stable public surface is the MCP server/tool boundary consumed by ADK-facing code.
- **Schema**: Pydantic models define every tool input, output envelope, telemetry block, error envelope, degraded response, and primary nested data entity.
- **Key models**: ToolDefinition, RequestContext, tool input/output schemas, telemetry envelope, error envelope, match state, fan hotspot, city event, venue, document result, team profile, and city profile.
- **Auth**: no authentication or authorization changes.
- **External services**: no external APIs are called in this slice; every tool defaults `allow_external` to false and reports `external_api_called: false`.
- **Cost controls**: request-level tool budget is required, cache is scoped to one request, cache hits do not consume budget, retries are capped at one, and timeouts return degraded responses.
- **Observability**: every tool response includes compact telemetry and every tool call emits trace metadata with latency, retries, degraded state, source type, cache hit, request ID, and trace ID.

---

## Phase 1: Centralize Schemas and Contracts

**User stories**: 8, 9, 15, 21, 22, 25, 30

### What to build

Introduce a shared schema layer for the MCP tool boundary. The slice should make one existing tool validate through typed schemas end to end, proving the schema pattern before all tools are migrated. The schema layer should cover input validation, output envelopes, telemetry, errors, degraded responses, and explicit source type values.

### Acceptance criteria

- [ ] Tool inputs and outputs can be validated through Pydantic models.
- [ ] Telemetry, error, and degraded response envelopes have stable typed shapes.
- [ ] Source type values are constrained to the agreed vocabulary.
- [ ] Invalid input returns the standard error envelope with telemetry.
- [ ] One existing tool proves the schema path through the MCP boundary.

---

## Phase 2: Canonical Registry and Middleware

**User stories**: 10, 11, 12, 13, 14, 16, 17, 18, 23, 24, 29

### What to build

Make the registry schema-aware and route tool execution through a canonical middleware layer. The middleware owns budget checks, cache checks, timeout execution, retry handling, telemetry normalization, degraded response generation, and trace emission. Compatibility shims may remain for existing imports while the new path becomes canonical.

### Acceptance criteria

- [ ] Tool definitions declare input schema, output schema, timeout, cacheability, retry cap, and description.
- [ ] Retry configuration above one is rejected.
- [ ] Budget exceeded returns a typed degraded response without invoking the handler.
- [ ] Timeout returns a typed degraded response.
- [ ] Retryable handler exceptions are retried at most once.
- [ ] Non-retryable errors are not retried.
- [ ] Trace metadata is emitted for success, degraded, and error responses.

---

## Phase 3: Request-Scoped Context and ADK Boundary

**User stories**: 12, 13, 14, 24, 27

### What to build

Ensure request-level budget and cache can be shared across multiple logical tool calls in one agent request. Add an ADK-facing call path or tests that prove agent-facing code can call MCP tools without bypassing the MCP/tool boundary.

### Acceptance criteria

- [ ] RequestContext carries request ID, trace ID, maximum tool calls, current call count, external access policy, and request cache.
- [ ] Duplicate validated inputs in the same request return cache hits.
- [ ] Cache hits do not increment tool call count.
- [ ] Attempted handler calls increment tool call count, including failures.
- [ ] Separate requests do not share cache entries.
- [ ] ADK-facing code can invoke registered tools through MCP.

---

## Phase 4: Complete the Seven-Tool Surface

**User stories**: 1-7, 19, 20, 26

### What to build

Migrate the existing five tools to the shared schema and middleware contracts, then add seeded `get_team_profile` and `get_city_profile`. All seven tools should be registered, locally callable, typed, cacheable where appropriate, and external-disabled by default.

### Acceptance criteria

- [ ] `get_match_state` is typed, registered, and callable through MCP.
- [ ] `get_fan_hotspots` is typed, registered, and callable through MCP.
- [ ] `get_city_events` is typed, registered, and callable through MCP.
- [ ] `get_venues` is typed, registered, and callable through MCP.
- [ ] `search_documents` is typed, registered, and callable through MCP.
- [ ] `get_team_profile` is typed, registered, and callable through MCP.
- [ ] `get_city_profile` is typed, registered, and callable through MCP.
- [ ] All tools default `allow_external` to false and report no external API calls.
- [ ] MCP server still starts locally.

---

## Phase 5: Trace, Degraded, and Cost Guardrails

**User stories**: 10, 11, 18, 19, 20, 21, 23, 28, 29

### What to build

Tighten guardrail behavior across all tools. Ensure degraded responses preserve typed empty data where practical, telemetry stays compact, source type is consistent, and traces contain the acceptance telemetry fields without verbose prompts, full documents, or excessive logs.

### Acceptance criteria

- [ ] Timeout degraded responses include required telemetry and typed empty data where practical.
- [ ] Budget degraded responses include required telemetry and typed empty data where practical.
- [ ] Every response includes latency, retry count, cache hit, degraded state, degraded reason, source type, request ID, trace ID, and external API status.
- [ ] Every trace includes latency, retries, degraded state, degraded reason, source type, request ID, and trace ID.
- [ ] No tool calls external APIs in local or test execution.
- [ ] Telemetry remains compact and does not include full prompts or full documents.

---

## Phase 6: Acceptance and Regression Coverage

**User stories**: 1-30

### What to build

Close the slice with behavior-level regression coverage for the full MCP tool foundation. Tests should verify public behavior through the MCP server, registry, context, and agent-facing boundary instead of private implementation details.

### Acceptance criteria

- [ ] Schema tests cover all seven tool inputs and outputs.
- [ ] Registry tests assert all seven tools are registered and definitions validate.
- [ ] Middleware tests cover budget, cache, timeout, retry, error, and degraded behavior.
- [ ] Tool tests call all seven tools through the MCP boundary.
- [ ] ADK boundary tests prove agent-facing MCP tool invocation.
- [ ] Existing MCP and fan gathering tests continue to pass.
- [ ] The relevant suite passes without live Gemini, Vertex, external APIs, paid inference, or network-only dependencies.
