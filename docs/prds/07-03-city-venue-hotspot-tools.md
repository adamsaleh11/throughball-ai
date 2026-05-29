# PRD: City, Venue, Event, and Hotspot MCP Tools

## Problem Statement

Throughball ADK agents need reliable city, venue, event, and supporter hotspot data through the MCP boundary, but the current tool surface is still too stub-like for production-style orchestration. Fan Gathering, City Concierge, and Itinerary agents need these tools to return contract-shaped seeded or cached data, preserve verified and inferred signals separately, expose confidence metadata, and obey the same budget, retry, and telemetry behavior established by the MCP foundation.

This matters now because downstream agents should synthesize and explain retrieved operational context, not perform deterministic ranking, filtering, hotspot scoring, or data access outside MCP. The AI repo also should not take on platform schema ownership in this ticket: platform Supabase tables may already exist for `host_cities` and `fan_hotspots`, while `venues`, `city_events`, and `tourist_spots` are expected to be handled by a separate Phase 01 platform/data effort. The AI repo needs an implementation boundary that works immediately with deterministic seeded data and can later swap to table-backed repositories without changing tool behavior.

## Solution

Implement `get_fan_hotspots`, `get_city_events`, `get_venues`, and `get_city_profile` as seeded/cached MCP tools backed by repository interfaces. Each tool will call a repository abstraction rather than raw fixtures or direct SQL. The initial implementation will use in-memory seeded repositories, while future Supabase-backed repositories can be introduced behind the same interfaces after the platform tables are verified and schema contracts are known.

Each tool will return responses shaped to the MCP contracts, including response-level `source_type`, standard telemetry, `external_api_called: false`, confidence metadata, and separate verified and inferred signal arrays. Top-level `data.verified_signals` and `data.inferred_signals` are the canonical deduped agent-facing signal sets. Item-level signals are provenance for individual venues, events, or hotspots and must not be merged by agent callers.

Valid requests with no matching filtered data return degraded responses with empty arrays and explicit degraded reasons. Invalid or missing required inputs return structured errors. Unknown `city_id` values are not treated as sparse data: they return not-found errors so agent bugs and ID typos do not silently masquerade as degraded data.

## User Stories

1. As a Fan Gathering Agent, I want to call `get_fan_hotspots`, so that I can explain supporter gathering candidates without calculating hotspot rankings myself.

2. As a Fan Gathering Agent, I want hotspot responses to include verified signals separately from inferred signals, so that I can communicate evidence quality honestly.

3. As a City Concierge Agent, I want to call `get_venues`, so that I can reference seeded venue records through MCP instead of hard-coding venue context.

4. As a City Concierge Agent, I want to call `get_city_events`, so that I can include matchday, nightlife, tourism, food, music, sports, or general event context without live external APIs.

5. As an Itinerary Agent, I want to call `get_city_profile`, so that I can format city-aware schedules with host city context, neighborhoods, transit summaries, and matchday notes.

6. As an ADK agent developer, I want all four tools to be callable through the existing MCP tool boundary, so that tool use remains traceable, cached, retried, and budgeted.

7. As an ADK agent developer, I want every tool response to expose `source_type`, so that agents can distinguish seeded, cached, user-generated, and external data.

8. As an ADK agent developer, I want `external_api_called` to remain false for these tools, so that I can trust the cost envelope and avoid accidental paid provider use.

9. As an ADK agent developer, I want top-level signal arrays to be deduped and canonical, so that multiple agents consume the same evidence set consistently.

10. As an ADK agent developer, I want item-level signal arrays to remain available as provenance, so that explanations can trace which item contributed which evidence.

11. As a backend engineer, I want tool handlers to depend on repository interfaces, so that future Supabase-backed implementations do not require changes to tool contracts or agent code.

12. As a backend engineer, I want in-memory seeded repositories now, so that the AI repo can ship deterministic behavior before platform tables are confirmed.

13. As a backend engineer, I want no migrations in this ticket, so that platform data ownership and AI orchestration remain cleanly separated.

14. As a backend engineer, I want missing required inputs to return `INVALID_INPUT`, so that malformed calls fail clearly.

15. As a backend engineer, I want unknown city IDs to return not-found errors, so that typos and agent routing bugs are not hidden as degraded sparse data.

16. As a backend engineer, I want valid filters with no matching data to return degraded empty responses, so that agents can continue gracefully when optional data is unavailable.

17. As an operator, I want responses to include standard telemetry from the MCP middleware, so that calls have trace IDs, request IDs, latency, retry count, cache state, source type, degraded state, and external API state.

18. As an operator, I want the one-retry cap and request-level tool budget to remain honored, so that tool execution stays low-cost and predictable.

19. As an evaluator, I want deterministic seeded data and no Gemini calls inside tools, so that MCP behavior is testable without model variability or external network dependencies.

20. As a future platform integrator, I want a clear place to add Supabase-backed repositories, so that platform tables can be adopted after their existence and schema are verified.

21. As a future platform integrator, I want empty Supabase-backed results to be reconsidered before caching, so that "not loaded yet" is not confused with "valid empty result" after real table access is introduced.

22. As a reviewer, I want manual smoke tests to call tools through the same boundary ADK agents use, so that acceptance checks reflect production access patterns.

## Implementation Decisions

- Four repository interfaces will be introduced: `HotspotsRepository`, `VenuesRepository`, `CityProfileRepository`, and `EventsRepository`.
- In-memory seeded implementations will be the default implementations for this ticket.
- Tool handlers will call repository interfaces and shape MCP responses. They will not own raw fixture filtering, Supabase SQL, external API calls, ranking, scoring, or AI synthesis.
- No Supabase migrations will be added in this ticket.
- No live external event APIs, Google Places API, paid map APIs, Gemini calls, or expensive model calls will be introduced.
- The shared `SourceType` schema will not be narrowed globally, because existing retrieval behavior uses broader source values. These four tools will only emit contract-compatible seeded/cached/user-generated/external source values, with seeded as the default for this slice.
- Response-level `source_type` remains required for MCP contract and telemetry behavior.
- Item-level `source_type` is acceptable for forward compatibility and provenance, especially where existing contracts or records already expose it.
- Top-level `data.verified_signals` and `data.inferred_signals` are the canonical deduped signal arrays for agent consumption.
- Item-level `verified_signals` and `inferred_signals` are provenance and should not be treated as separate canonical signal sets by agents.
- Confidence metadata will be returned under `data.confidence`. Item-level confidence strings may remain where contracts already show them.
- Missing required fields return structured errors, not degraded responses.
- Unknown `city_id` values return not-found errors for every city-scoped tool.
- Valid requests with no matching optional filters return `ok: true`, empty result arrays, degraded telemetry, and tool-specific degraded reasons.
- `get_fan_hotspots` may return precomputed seeded hotspot scores from the repository, but the tool must not calculate scores.
- `get_venues` and `get_city_events` may apply deterministic repository-owned filtering for type, category, neighborhood, and dates.
- `get_city_profile` distinguishes an unknown city from a known city with partial optional profile data.
- The existing MCP middleware remains responsible for standard telemetry, request-level tool budgets, caching, timeouts, and retry count.
- A thin `call_tool` helper may be added if needed to satisfy the documented smoke-test import path, but it must call through the established MCP boundary rather than bypassing it.

## Testing Decisions

- Tests should verify external behavior and contracts, not repository internals.
- MCP tool tests should assert that all four tools are registered and callable through the MCP server.
- Contract-shape tests should validate successful responses against declared output schemas.
- Tests should assert `source_type` is visible, `external_api_called` remains false, and standard telemetry is present.
- Tests should assert top-level `data.verified_signals` and `data.inferred_signals` are present and remain separate.
- Tests should assert item-level signals remain available for provenance where returned records include them.
- Tests should assert unknown `city_id` returns not-found errors instead of degraded empty data.
- Tests should assert missing required inputs return `INVALID_INPUT`.
- Tests should assert valid no-match filters return degraded empty responses rather than exceptions.
- Tests should assert `get_fan_hotspots` does not require any Gemini or external API dependency.
- Tests should include the manual smoke-test path using the public tool boundary: calling `get_venues` with a Toronto city ID and checking `source_type == "seeded"` plus the presence of `verified_signals`.
- Existing MCP tests and registry tests provide prior art for tool registration, schema validation, telemetry, and invalid input handling.

## Out of Scope

- Adding or modifying Supabase migrations.
- Creating platform tables for `host_cities`, `fan_hotspots`, `venues`, `city_events`, or `tourist_spots`.
- Implementing live Supabase-backed repositories before table existence and schema are confirmed.
- Calling external event, places, maps, or geocoding APIs.
- Calling Gemini or any model from inside MCP tools.
- Implementing deterministic ranking, itinerary ordering, or hotspot scoring in the AI/tool layer.
- Changing ADK agent synthesis behavior beyond ensuring tools are callable through MCP.
- Rewriting shared retrieval schemas or breaking `search_documents` behavior.
- Adding broad production observability infrastructure beyond existing MCP telemetry.

## Further Notes

- Platform Supabase may already contain `host_cities` and `fan_hotspots` from earlier platform phases. The AI repo currently does not have the database URL needed to verify that directly.
- The recommended SQL check for the platform Supabase SQL editor is:
  `select table_name from information_schema.tables where table_schema = 'public' and table_name in ('host_cities','fan_hotspots','venues','city_events','tourist_spots');`
- If `host_cities` and `fan_hotspots` exist in platform Supabase, a later ticket can introduce Supabase-backed repositories for those two data sources first.
- If those tables are missing, that mismatch should be flagged against the platform/data plan because any fan heatmap UI depending on them would not be rendering real table-backed data.
- Empty degraded responses are cacheable for deterministic in-memory seeded repositories. A future Supabase-backed implementation should reconsider caching empty results because an empty database response may mean data has not been loaded yet rather than no match exists.
- This feature should preserve the repo's low-cost orchestration-first philosophy: deterministic preprocessing and data access belong behind repositories; AI agents consume and explain the results.

