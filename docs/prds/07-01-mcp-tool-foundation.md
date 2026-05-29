# PRD: MCP Tool Foundation

## Problem Statement

Throughball needs an MCP tool layer that ADK agents can use as the only structured data access boundary. The repo already has an MCP server foundation, several seeded tools, telemetry helpers, request context, and agent code that calls MCP tools, but the tool layer is still incomplete for the next system slice. It lacks a fully typed schema module, a canonical middleware layer, two required profile tools, and a request-scoped budget/cache model that clearly survives across multiple logical tool calls in one agent request.

This matters because agents must be able to explain, synthesize, route, and summarize over structured evidence without directly reaching into deterministic data logic, external APIs, or ad hoc dictionaries. The tool layer is the contract that keeps cost low, observability consistent, and downstream ADK agents safe from uncontrolled retries, missing telemetry, and invented data access behavior.

## Solution

Build the MCP tool foundation that exposes seven structured tools to ADK agents: `get_fan_hotspots`, `get_city_events`, `get_venues`, `search_documents`, `get_match_state`, `get_team_profile`, and `get_city_profile`.

Every tool will have Pydantic input and output schemas, a registry definition with timeout and retry configuration, a canonical middleware execution path, request-level budget enforcement, request-scoped result caching, degraded responses, and compact telemetry. The implementation will remain low-cost and orchestration-first: no external APIs are called by default, `allow_external` defaults to false, retries are capped at one, and seeded or internal data stands in for future real integrations.

The outcome is a locally runnable MCP server whose tools are registered, callable through the MCP boundary, compatible with ADK agent usage, and observable through response telemetry and trace events.

## User Stories

1. As an ADK agent, I want to call `get_match_state`, so that I can explain match context using structured match data.
2. As an ADK agent, I want to call `get_fan_hotspots`, so that I can explain supporter gathering candidates without calculating hotspot ranking myself.
3. As an ADK agent, I want to call `get_city_events`, so that I can include matchday event context in synthesis.
4. As an ADK agent, I want to call `get_venues`, so that I can reference venue records and venue metadata through the MCP boundary.
5. As an ADK agent, I want to call `search_documents`, so that I can retrieve evidence snippets for grounded synthesis.
6. As an ADK agent, I want to call `get_team_profile`, so that I can use stable team context, supporter notes, aliases, and evidence references.
7. As an ADK agent, I want to call `get_city_profile`, so that I can use stable city context, neighborhoods, transport notes, matchday notes, and safety notes.
8. As an ADK agent, I want every tool response to include typed data and telemetry, so that I can reason over predictable response contracts.
9. As an ADK agent, I want invalid inputs to return a structured error envelope, so that I can distinguish caller mistakes from degraded data availability.
10. As an ADK agent, I want timeouts to return degraded responses, so that one slow tool does not force the whole agent response to fail.
11. As an ADK agent, I want budget-exceeded calls to return degraded responses, so that uncontrolled tool loops are stopped without encouraging model retries.
12. As an ADK agent, I want cached results for duplicate calls in the same request, so that repeated lookups do not consume extra backend work.
13. As an ADK agent, I want cache hits not to count against the request tool budget, so that repeated identical inputs remain cheap.
14. As an ADK agent, I want failed attempted calls to count against the request tool budget, so that retries and failures are still bounded.
15. As a developer, I want all tool input and output schemas centralized, so that the MCP and ADK boundary is inspectable and testable.
16. As a developer, I want tool registration to be explicit, so that required tools are easy to audit and tests can assert the full tool surface.
17. As a developer, I want each tool definition to declare timeout, cacheability, and retry configuration, so that per-tool cost controls are clear.
18. As a developer, I want retry count capped at one, so that transient failures can recover without runaway latency or cost.
19. As a developer, I want no external APIs called by default, so that local development and CI remain deterministic and cheap.
20. As a developer, I want `allow_external` to default to false on every tool input, so that external access must be explicit in future integrations.
21. As a developer, I want every tool response to report whether an external API was called, so that cost and provenance stay visible.
22. As a developer, I want every tool response to include `source_type`, so that agents can distinguish seeded, cached, internal, external, and unavailable data.
23. As a developer, I want every tool call to emit trace metadata, so that latency, retries, cache hits, degraded mode, and source type are observable.
24. As a developer, I want request-level budget and cache to be represented in request context, so that ADK agent runs can share state across multiple tool calls.
25. As a developer, I want typed degraded responses with valid empty data structures where possible, so that downstream agents do not need special-case parsing for every failure mode.
26. As a developer, I want the existing MCP server to continue starting locally, so that this ticket does not regress local tool development.
27. As a developer, I want ADK-facing tests or adapters to prove tools are callable through the MCP/tool boundary, so that agents do not bypass MCP.
28. As an operator, I want telemetry to stay compact, so that traces contain useful summaries, metrics, and IDs without full prompts, full documents, or noisy logs.
29. As an operator, I want degraded reasons to be explicit, so that timeout, budget, disabled external access, and data-unavailable cases can be diagnosed.
30. As a future tool implementer, I want a consistent pattern for adding new tools, so that additional data sources can be introduced without rewriting middleware or telemetry code.

## Implementation Decisions

- The MCP tool layer will expose exactly seven required tools for this slice: `get_fan_hotspots`, `get_city_events`, `get_venues`, `search_documents`, `get_match_state`, `get_team_profile`, and `get_city_profile`.
- Tool access remains exclusively through MCP. ADK agents must call the MCP/tool boundary rather than importing backend data functions directly.
- Typed schemas will be centralized in a schema module using Pydantic models for all tool inputs, output envelopes, telemetry, errors, and nested data entities.
- Primary nested entities will be modeled explicitly: hotspot, city event, venue, document search result, match state, team profile, city profile, telemetry, and error details.
- Tool definitions will include the tool name, handler, input schema, output schema, timeout, cacheability, max retry count, and description.
- Tool registration will remain explicit rather than filesystem-autodiscovered. Tests should assert the full required tool set is registered.
- A canonical middleware layer will own budget checks, cache checks, timeout execution, retry handling, telemetry normalization, degraded response generation, and trace emission.
- Existing wrapper imports may remain as compatibility shims while the canonical execution path moves to middleware.
- Request context will carry request ID, trace ID, request-level maximum tool calls, current tool call count, `allow_external` default policy, and per-request cache.
- Request-level cache keys will be built from tool name plus a canonical hash of validated input values, including defaults, so equivalent calls reuse cached results.
- Cache hits will not increment the request tool call count.
- Calls that reach the handler will increment the request tool call count, including calls that fail after execution starts.
- Budget-exceeded responses will be typed degraded responses with `ok: true`, `degraded: true`, `degraded_reason: TOOL_BUDGET_EXCEEDED`, telemetry, and empty data where practical.
- Invalid input responses will be structured hard errors with `ok: false`, `error.code: INVALID_INPUT`, and `degraded: false`.
- Timeout responses will be typed degraded responses rather than hard errors.
- Timeouts will not be retried by default. Retry is reserved for explicitly retryable transient handler exceptions.
- Tool retries are capped at one. Tool definition validation must reject retry counts above one.
- Every tool input will include `allow_external` defaulting to false.
- No external APIs will be called in this ticket, even when a caller passes `allow_external: true`. Unsupported external access may be reported as degraded in future integrations.
- Tool response telemetry will include request ID, trace ID, latency, retry count, cache hit, degraded state, degraded reason, source type, and external API call status.
- Trace events will record the compact lifecycle metadata needed for observability, including latency, retries, degraded state, cache hit, source type, and IDs.
- `source_type` values will be constrained to a small vocabulary such as seeded, cached, internal, external, and none.
- Seeded data may include fixed backend-style scores and ordering to represent deterministic backend output. Agents must not calculate ranking, filtering, hotspot scores, or itinerary ordering.
- `get_team_profile` will return seeded or internal team context including team ID, name, country, aliases, supporter notes, rivalries, known supporter areas, evidence IDs, source type, and last updated timestamp.
- `get_city_profile` will return seeded or internal city context including city ID, name, country, timezone, neighborhoods, transport notes, matchday notes, safety notes, source type, and last updated timestamp.
- Local MCP startup remains part of the acceptance surface. The server should be buildable and locally runnable with the existing project dependency model.
- ADK callability for this ticket means tools can be invoked through the MCP server/tool boundary from agent-facing code or tests. A full live ADK agent loop is not required in this slice.

## Testing Decisions

- Tests should assert external behavior and stable contracts rather than private implementation details.
- Schema tests should validate all seven tool input models, output models, telemetry models, degraded envelopes, and error envelopes.
- Registry tests should assert all seven tools are registered, definitions validate, retry caps are enforced, and schema references are present.
- Middleware tests should cover budget exceeded, cache hit, cache miss, timeout degradation, retryable exception recovered after one retry, retryable exception exhausted, and non-retryable exception not retried.
- Request context tests should cover request-scoped cache isolation, canonical input hashing, call count behavior, and cache hits not incrementing budget.
- Tool tests should call each required tool through the MCP server boundary and assert typed response shape, telemetry fields, default `allow_external: false`, and `external_api_called: false`.
- Tool error tests should verify missing required inputs return `INVALID_INPUT` with the standard error envelope and telemetry.
- Degraded response tests should verify budget and timeout degraded responses include typed empty data structures where practical.
- Trace tests should verify emitted tool telemetry includes latency, retries, degraded state, degraded reason, cache hit, source type, request ID, and trace ID.
- ADK boundary tests should verify agent-facing code can call the registered tools through MCP without direct backend imports.
- Regression tests should keep existing fan gathering and MCP tests passing while the schema and middleware layers become stricter.
- Tests must not require live Gemini, Vertex credentials, external APIs, network-only services, or paid inference.

## Out of Scope

- Live external API integrations.
- Supabase-backed or database-backed real implementations of the seven tools.
- Real-time crowd detection or live supporter tracking.
- Model-based ranking, filtering, hotspot scoring, city recommendation ranking, or itinerary sequencing.
- Gemini Pro, expensive reasoning models, or any new model policy changes.
- Full ADK orchestration loop changes beyond proving MCP tool callability.
- Authentication, authorization, user profiles, saved preferences, or personalization.
- Production deployment, hosted observability dashboards, or paid tracing sinks.
- Large fixture sets, full prompt dumps, verbose trace logs, or full document storage in telemetry.

## Further Notes

- This PRD assumes the existing MCP server, seeded tools, telemetry helpers, settings, and tests are the starting point. The work should evolve the current implementation rather than replacing it wholesale.
- The architecture must preserve the repo principle that AI explains, synthesizes, orchestrates, routes, and summarizes. Deterministic ranking, filtering, scoring, and ordering belong in backend logic outside the AI layer.
- The source-of-truth behavior for this slice is the MCP/tool boundary: agents consume typed tool responses and compact telemetry, not internal data structures.
- Request-level budget/cache needs special attention because creating a fresh context per individual tool call does not satisfy the intended cross-tool request behavior for ADK agent runs.
- Seeded data should stay intentionally small and coherent. The goal is to demonstrate production orchestration discipline, not a large data catalog.
