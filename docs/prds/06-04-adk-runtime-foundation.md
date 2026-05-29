# PRD: ADK Runtime Foundation

## Problem Statement

Throughball-ai needs a concrete Google ADK runtime foundation before later agent tickets can safely move from deterministic orchestration and mocked synthesis into ADK-backed execution. The repo already has local runtime configuration, Flash-only model routing, MCP contracts, compact telemetry helpers, and a fan agent boundary, but it does not yet have an ADK-specific runtime module, model configuration adapter, session/state service, callback hooks, or normalized LLM-native metrics.

This matters because ADK should become the primary agent framework without weakening the repo's low-cost, orchestration-first discipline. Future agents need a shared runtime boundary that initializes locally, enforces Gemini Flash as the default model, keeps Gemini Pro disabled by default, caps model output, limits agent iterations, tracks useful model metrics, and prevents session state from growing into a hidden prompt or document store.

## Solution

Create an ADK runtime foundation for throughball-ai that adapts the existing settings, model router, telemetry, and MCP-first tool philosophy into an ADK-ready module set. The foundation should initialize locally without live Gemini, Vertex, ADK server, MCP network, or paid model calls. It should expose small, stable interfaces for runtime construction, model configuration, compact session state, callback tracing, and metrics normalization.

The runtime will make Gemini Flash the default model and preserve deterministic model routing as the source of truth. The session layer will keep state intentionally small by storing compact task state, retrieval references, short summaries, counters, and degraded status only. Callback hooks will emit compact structured telemetry for model, agent, and tool lifecycle events without logging full prompts, completions, retrieved documents, secrets, or private user data. Metrics will include token counts, latency, tokens per second, estimated cost, cost per request, model name, tool call count, retry count, and degraded status.

This ticket creates the foundation only. It does not migrate existing agents to ADK execution, implement live model inference, introduce Gemini Pro, or change MCP tool semantics.

## User Stories

1. As an agent developer, I want an ADK runtime foundation, so that future throughball-ai agents can share one framework boundary.
2. As an agent developer, I want the ADK runtime to initialize locally, so that development and CI do not require live credentials or paid inference.
3. As an agent developer, I want runtime construction to avoid live Gemini, Vertex, ADK server, or MCP network calls, so that initialization remains deterministic and cheap.
4. As an agent developer, I want ADK model configuration to load from existing environment settings, so that model policy stays centralized.
5. As an agent developer, I want Gemini Flash to be the default ADK model, so that the repo's low-cost policy is enforced by the runtime.
6. As an agent developer, I want Gemini Pro disabled by default, so that expensive models cannot silently enter the agent path.
7. As an agent developer, I want max output tokens configured for ADK model calls, so that future completions are bounded.
8. As an agent developer, I want factual temperature to come from existing settings, so that ADK behavior matches current model-routing policy.
9. As an agent developer, I want model routing to remain deterministic and side-effect free, so that route selection can be tested without model calls.
10. As an agent developer, I want per-agent max iteration limits, so that no ADK agent can create autonomous infinite loops.
11. As an agent developer, I want a default max iteration limit, so that agents remain bounded even before agent-specific tuning exists.
12. As an agent developer, I want compact ADK session state, so that sessions preserve task continuity without storing large documents or prompt history.
13. As an agent developer, I want retrieval references and short summaries stored in state, so that future RAG agents can cite evidence without carrying full retrieved documents.
14. As an agent developer, I want session state helpers to reject or avoid runaway context growth, so that state hygiene is enforced by design.
15. As an agent developer, I want runtime state to track iteration and tool-call counters, so that loops and tool usage can be observed and bounded.
16. As an agent developer, I want callback hooks for agent lifecycle events, so that agent runs can be traced consistently.
17. As an agent developer, I want callback hooks for model lifecycle events, so that latency, usage, cost, and degradation can be tracked.
18. As an agent developer, I want callback hooks for tool lifecycle events, so that ADK orchestration remains compatible with MCP tracing expectations.
19. As an operator, I want compact structured callback logs, so that local telemetry can be inspected without hosted observability infrastructure.
20. As an operator, I want callback logs to avoid full prompts, completions, retrieved documents, secrets, and private user data, so that observability remains low-risk.
21. As an operator, I want LLM-native metrics to include prompt, completion, and total tokens, so that model usage is visible.
22. As an operator, I want LLM-native metrics to include latency and tokens per second, so that runtime performance can be measured.
23. As an operator, I want LLM-native metrics to include estimated cost and cost per request, so that low-cost operation can be audited.
24. As an operator, I want LLM-native metrics to include model name, tool call count, retry count, and degraded status, so that operational summaries remain compact but useful.
25. As a reviewer, I want tests for ADK runtime initialization, so that the foundation can be validated without external services.
26. As a reviewer, I want tests for Flash-only model configuration and Pro-disabled behavior, so that model policy regressions are caught.
27. As a reviewer, I want tests for compact session state behavior, so that full retrieved documents and runaway state growth are not normalized.
28. As a reviewer, I want tests for callback telemetry shape, so that tracing stays aligned with existing observability contracts.
29. As a reviewer, I want tests for derived metrics such as tokens per second and cost per request, so that metric semantics are clear.
30. As a future agent implementer, I want this ticket to stop before migrating concrete agents, so that the runtime foundation can be reviewed independently.

## Implementation Decisions

- The implementation target is throughball-ai. Any `worldpulse-ai` references in the originating ticket are stale rename artifacts.
- Google ADK is the primary future agent framework, but this ticket creates a local foundation rather than a full ADK agent workflow.
- The ADK runtime module will be introduced under the existing throughball-ai package namespace.
- The ADK runtime will reuse existing typed settings and model routing as the source of truth for model name, temperature, and output token caps.
- ADK model configuration will be an adapter over existing route metadata, not an independent second model policy system.
- Gemini Flash is the default and only enabled model path for this ticket.
- Gemini Pro is disabled by default. Any future support for Pro must require an explicit policy change and setting rather than accidental routing.
- Max output tokens remain configured through environment-backed settings.
- A default max agent iteration limit will be added and can be overridden per agent by future runtime callers.
- Runtime initialization means constructing local runtime/config/session/callback objects successfully. It does not mean making a live provider inference call.
- The runtime will avoid live Gemini, Vertex, ADK server, MCP network, or external service calls during initialization and unit tests.
- The session service will start as an in-memory compact state service.
- Session state will store only compact task state, IDs, retrieval references, short summaries, iteration count, tool-call count, retry count, selected model, and degraded status.
- Session state will not store full retrieved documents, full prompts, full completions, large transcript histories, secrets, API keys, or private user data.
- Session helpers should make compact state the easiest path by providing explicit methods for summaries, retrieval references, and counters.
- Callback hooks will provide stable local lifecycle interfaces for agent, model, and tool events even if future ADK integration requires adapter glue.
- Callback telemetry will align with the existing observability vocabulary and remain compact JSON.
- LLM metrics will be normalized into one stable metric payload shape.
- `estimated_cost` represents the estimated cost for the current model call or span.
- `cost_per_request` equals the model-call cost for a single-call span and can become an aggregate request total when future orchestration combines multiple model calls.
- `tokens_per_second` is calculated from completion tokens and positive latency. Missing or zero latency produces `0.0`.
- Tool call count for ADK metrics will come from runtime/session counters and MCP boundaries, not from model-generated claims.
- Retry count defaults to zero and should be explicit when future bounded retries are added.
- MCP remains the only tool access boundary. ADK integration must not bypass MCP tracing, latency, retry, degraded, and budget behavior.
- This foundation should preserve the repo rule that AI explains, synthesizes, orchestrates, routes, and summarizes, while deterministic ranking, filtering, scoring, hotspot calculation, and itinerary ordering stay in backend logic.

## Testing Decisions

- Tests should verify public runtime behavior, configuration contracts, session contracts, callback payloads, and metric semantics rather than private helper internals.
- Runtime tests should verify the ADK foundation initializes locally without live Gemini, Vertex, ADK server, MCP network, or external service calls.
- Model config tests should verify Gemini Flash loads from environment-backed settings and that Gemini Pro is disabled by default.
- Model config tests should verify max output tokens, temperature, and max iteration defaults are present and bounded.
- Session tests should verify session state exists, can store compact task state, can store retrieval references and short summaries, and tracks counters.
- Session tests should verify full retrieved document-like payloads are not stored as session state by default.
- Callback tests should verify compact structured events are emitted for model and lifecycle hooks with required IDs, latency, retry, degraded, and model fields.
- Metrics tests should verify prompt tokens, completion tokens, total tokens, tokens per second, latency, estimated cost, cost per request, model name, tool call count, retry count, and degraded fields.
- Metrics tests should verify missing provider usage metadata is handled with safe zero/default values.
- Existing telemetry tests provide prior art for compact JSON event assertions and cost estimation behavior.
- Existing model router tests provide prior art for Flash-only routing assertions.
- Existing MCP context and wrapper tests provide prior art for counters, tool budgets, degraded behavior, and compact request state.
- No tests should require paid inference, live Google credentials, live Vertex, live Gemini, a running ADK service, hosted telemetry, or external network calls.

## Out of Scope

- Migrating the existing Fan Gathering Agent to ADK execution.
- Implementing full ADK agent workflows or multi-agent orchestration.
- Live Gemini model execution.
- Gemini Pro or expensive reasoning model support.
- Automatic model escalation to a higher-cost model.
- Autonomous infinite loops, recursive agent calls, or unbounded retries.
- Bypassing MCP for tool access.
- Persisted database-backed ADK sessions.
- Storing full retrieved documents, full prompts, full completions, or long conversation histories in state.
- Backend ranking, filtering, hotspot scoring, itinerary sequencing, or deterministic candidate ordering.
- Hosted observability dashboards or mandatory remote telemetry exporters.
- Auth, user profiles, deployment infrastructure, or database schema changes.

## Further Notes

- This PRD assumes the prior AI runtime foundation remains in place and that ADK-specific modules layer on top of it.
- The observability contract is the source of truth for telemetry vocabulary. ADK metrics may add acceptance-specific aliases, but should not drift from existing event semantics.
- The MCP contracts remain the source of truth for tool response shape, timeout behavior, retries, degraded responses, and tool telemetry.
- The first implementation should prefer small, typed, testable local objects over deep coupling to ADK internals. Future tickets can adapt these objects to exact ADK callback signatures as concrete agents are migrated.
- The local developer workflow should remain cheap and deterministic from a copied `.env` file.
