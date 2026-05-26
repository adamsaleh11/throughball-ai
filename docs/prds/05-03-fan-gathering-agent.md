# PRD: Fan Gathering Agent

## Problem Statement

Throughball needs a Fan Gathering Agent that can answer practical supporter-location questions such as where Argentina fans are gathering, where to watch with Brazil fans, and which fan zone is active. Today the repo has runtime, model-routing, telemetry, and partial MCP foundations, but no fan-facing agent layer and no complete MCP tool surface for fan gathering.

This matters because fan intelligence is a core demo slice for the AI system. The feature must show credible GenAI orchestration without letting the model invent live crowd activity, calculate deterministic rankings, or call expensive/external services. The system should demonstrate grounded synthesis, uncertainty handling, model routing, bounded tool use, and low-cost production discipline.

## Solution

Build a Fan Gathering Agent that answers fan-location questions using exactly the required MCP tool surface: `get_fan_hotspots`, `get_city_events`, and `get_venues`. The agent will gather seeded or cached data through MCP, preserve verified and inferred evidence separately, compute confidence through deterministic and inspectable rules, and synthesize a short grounded answer.

The production path will support one real Gemini Flash model execution path for answer synthesis. Local tests will use deterministic or mocked model execution so CI never requires live Vertex/Gemini credentials or paid inference. The agent will route through the existing Gemini Flash model policy, never use Gemini Pro, never call external live event APIs, and never present cached or seeded records as live real-time certainty.

The result should be an observable, low-cost, safe AI agent: three bounded tool calls, short output, explicit confidence, compact evidence summary, source attribution, degraded handling, and lightweight agent telemetry.

## User Stories

1. As a fan, I want to ask where Argentina fans are gathering, so that I can find a likely supporter spot without manually searching multiple sources.
2. As a fan, I want to ask for the best place to watch with Brazil fans, so that I can choose a venue with relevant supporter signals.
3. As a fan, I want to ask which fan zone is active, so that I can decide whether a matchday area is worth visiting.
4. As a fan, I want answers to distinguish verified signals from inferred signals, so that I understand how grounded the recommendation is.
5. As a fan, I want the answer to include confidence, so that I know whether the system is making a strong recommendation or a cautious suggestion.
6. As a fan, I want low-confidence answers to be explicit and safe, so that I am not misled by weak or stale data.
7. As a fan, I want the agent to avoid claims of live certainty when using cached or seeded data, so that I understand the answer is not real-time crowd tracking.
8. As a fan, I want short answers by default, so that I can quickly decide where to go.
9. As a developer, I want the agent to call `get_fan_hotspots`, `get_city_events`, and `get_venues` through MCP, so that tool access remains traceable, cached, retried, and budgeted.
10. As a developer, I want the missing `get_city_events` and `get_venues` MCP tools to return seeded or cached contract-shaped data, so that the agent can be built and tested before real data sources are wired.
11. As a developer, I want the agent to make at most three tool calls per request, so that fan gathering remains cost-controlled and resistant to tool loops.
12. As a developer, I want tool calls to run concurrently with timeout isolation, so that one degraded tool does not block synthesis from the other available tool results.
13. As a developer, I want the agent to force `allow_external: false` on all tool calls, so that no live external event APIs are called in this slice.
14. As a developer, I want the agent to support both direct `team_id` input and deterministic team alias parsing, so that natural questions like “Argentina fans” work without LLM-based parsing.
15. As a developer, I want team alias parsing to be a small deterministic map, so that model cost and parsing uncertainty stay low.
16. As a developer, I want confidence to be computed deterministically from inspectable inputs, so that outputs can be debugged and explained.
17. As a developer, I want confidence downgrade reasons to be available, so that low-confidence or degraded responses are operationally understandable.
18. As a developer, I want the agent to preserve backend hotspot ordering and not calculate hotspot scores, so that deterministic ranking remains outside the AI layer.
19. As a developer, I want the production synthesis path to support Gemini Flash, so that the feature demonstrates real Google GenAI integration.
20. As a developer, I want tests to mock or bypass live Gemini calls, so that the test suite remains deterministic, cheap, and credential-free.
21. As a developer, I want the selected model route to be observable, so that Gemini Flash-only policy can be verified.
22. As an operator, I want lightweight agent telemetry with agent name, tool call count, selected model, and degraded status, so that fan gathering runs can be inspected without verbose logs.
23. As an operator, I want tool source attribution in the agent response, so that I can see whether the answer came from seeded, cached, or degraded data.
24. As an operator, I want response length to respect a configurable cap, so that model output cost and user-facing verbosity remain bounded.

## Implementation Decisions

- The Fan Gathering Agent will be the first concrete fan-facing agent boundary in the AI runtime.
- The agent will answer supporter gathering, watch-with-fans, and active-fan-zone questions using a shared fan gathering request/response contract.
- The request contract will support structured inputs such as `city_id`, `match_id`, optional `team_id`, optional natural-language `question`, optional date window, and optional output length cap.
- The agent will support deterministic team alias parsing for a small configured set of aliases such as Argentina, Brazil, and Canada. Alias parsing will not use an LLM.
- The agent will make no more than three logical MCP tool calls for one answer: `get_fan_hotspots`, `get_city_events`, and `get_venues`.
- The missing `get_city_events` and `get_venues` MCP tools will be added as seeded or cached stubs that follow the existing MCP contract shapes.
- All tool access will go through the MCP tool boundary so timeout, retry, cache, budget, telemetry, and degraded behavior remain centralized.
- The agent will call tools with `allow_external: false` and will not call live external event APIs.
- Tool calls may run concurrently, but each result must be isolated so one exception, timeout, or degraded response does not discard successful results from other tools.
- The agent will synthesize from available tool results even when one tool is degraded or unavailable.
- The agent will use backend-provided hotspot order and confidence metadata. It will not calculate hotspot scores, perform model-based ranking, or reorder itinerary-like results.
- Confidence will be computed through deterministic rules. Inputs will include verified signal count, inferred signal count, tool source types, matching venue/event support, degraded tool status, empty result state, and seeded/cached freshness limitations.
- Confidence output will include a top-level confidence label and inspectable confidence details, including contributors and downgrade reasons.
- Verified and inferred signals will remain separate in internal data and final responses.
- The production synthesis path will support a real Gemini Flash model adapter. The adapter will be routed through the existing model router and must not introduce Gemini Pro or expensive reasoning models.
- Tests will not require live Gemini or Vertex credentials. They will use deterministic synthesis or a mocked model adapter while still asserting that Gemini Flash route metadata is selected.
- Responses will be short by default and bounded by a configurable output length cap.
- Agent responses must not present cached or seeded data as live real-time certainty. Acceptable phrasing includes “cached matchday data suggests” or “seeded data lists”; unacceptable phrasing includes claims that fans are “currently gathering” unless a future live verified source explicitly supports that.
- The agent response will include compact source attribution such as tool name, source type, degraded state, and cache/external-call status where available.
- Lightweight agent telemetry will record agent name, logical tool calls, selected model, degraded status, and compact confidence state. It will avoid full prompts, completions, and verbose evidence dumps.

## Testing Decisions

- Tests should cover external behavior and contracts rather than private helper implementation details.
- MCP tests should verify `get_city_events` and `get_venues` are registered, callable, seeded/cached, and contract-shaped.
- Agent tests should verify that a normal fan gathering request returns an answer, confidence, evidence summary, verified signals, inferred signals, confidence details, tool sources, and degraded status.
- Agent tests should verify low-confidence behavior when results are empty, mostly inferred, seeded-only, or degraded.
- Agent tests should verify that cached or seeded data is not phrased as live real-time certainty.
- Agent tests should verify deterministic alias parsing for supported team names and safe behavior for unknown team names.
- Agent tests should verify the agent attempts no more than three logical tool calls for one answer.
- Agent tests should verify all tool calls use `allow_external: false` and that returned telemetry does not report external API calls.
- Model-routing tests should verify the selected model is Gemini Flash and that Gemini Pro does not appear in the agent path.
- Model adapter tests should verify the live Gemini adapter boundary can be constructed from configuration without making live calls during unit tests.
- Synthesis tests should use deterministic or mocked model execution; no test should require live Vertex AI, Gemini, MCP network transport, or external event APIs.
- Telemetry tests should verify compact agent telemetry includes agent name, selected model, tool call count, degraded state, and confidence state without logging full prompt or completion text.
- Output tests should verify the response remains under the configured output length cap.

## Out of Scope

- Gemini Pro or expensive reasoning model support.
- Live external event APIs or real-time crowd detection.
- Model-based hotspot ranking, filtering, scoring, or itinerary sequencing.
- Full city concierge recommendations beyond fan gathering and watch-location explanation.
- Full itinerary generation or schedule ordering.
- Broad retrieval loops or additional tools beyond `get_fan_hotspots`, `get_city_events`, and `get_venues`.
- Production Supabase-backed implementations of the three tools.
- Auth, user profiles, personalization, saved preferences, or push notifications.
- Hosted observability dashboards or paid tracing platforms.
- Full eval suite beyond focused acceptance tests for this slice.

## Further Notes

- The MCP contracts are the source of truth for tool response shape, error behavior, timeout behavior, and degraded response semantics.
- The observability contract is the source of truth for telemetry vocabulary. Any new agent telemetry fields should remain compact and compatible with future request summaries.
- The feature should preserve the repo’s core rule: AI explains, synthesizes, orchestrates, routes, and summarizes; deterministic ranking, filtering, scoring, and ordering belong outside model prompts.
- The real Gemini Flash path is important for demonstrating Google Cloud GenAI readiness, but the default developer and test workflow must remain cheap and deterministic.
- Seeded data should be intentionally small and coherent: enough to demonstrate Argentina/Brazil/Canada fan questions, venue enrichment, event support, confidence downgrades, and source attribution without creating a large fixture maintenance burden.
