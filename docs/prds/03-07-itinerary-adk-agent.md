# PRD — 03-07 Itinerary ADK Agent

Status: Ready for planning
Phase: 03 (ADK agents)
Depends on: 03-02 (MCP server foundation), Phase 02 tools (`get_venues`, `get_city_events`), 03-05/03-06 agent patterns
Source contract: `docs/contracts/mcp_contracts.md` (`generate_itinerary`, `get_route_context`)

## Problem Statement

A World Cup traveler arriving in a host city wants a concrete, day-by-day plan: where to go before and after the match, which supporter pubs and fan zones fit their budget and interests, and how those stops relate to the match schedule. Today the Throughball platform exposes an `/itineraries/generate` capability in its contracts, but the agent that fulfills it was never built — it was specified in an early document, dropped in a later revision, and is now being restored as a Google ADK agent.

Two of the MCP tools this capability depends on, `generate_itinerary` and `get_route_context`, are listed in the MCP contracts (ticket 01-02) but were never implemented. Without them and without the agent, the platform cannot turn seeded venue, event, and match data into a structured, reasoned, budget-aware itinerary. This matters now because the surrounding agents (City Concierge, Match Analyst, Fan Gathering) already ship on ADK, and the itinerary capability is the remaining gap in the matchday companion experience.

## Solution

Build an `ItineraryADKAgent` on Google ADK that produces a multi-day, match-aware itinerary from seeded data, plus the two missing MCP tools it depends on.

From the user's perspective: given a city, a match, a traveler profile (party size, interests, budget, accessibility needs), and a date range, the agent returns an itinerary structured by day, where each day holds a small ordered list of items (venues and events) with start/end times and a short explanation of why each item was chosen. The response includes the agent's reasoning, an explicit confidence label, and a list of assumptions — including an honest statement of how sequencing was derived. When data is missing or a tool degrades, the agent still returns a usable, clearly-marked partial itinerary rather than failing.

The agent's LLM (Gemini Flash) owns the planning: it gathers candidate venues and events, optionally checks approximate route context between key points, filters by budget and interests, and produces an ordered list of candidates. The `generate_itinerary` tool is a pure, deterministic formatter — it takes the ordered candidate IDs and lays them onto days and time slots using a matchday-anchored heuristic. It does not invent ordering or perform geographic optimization, and the response says so plainly.

Sequencing is **matchday-anchored, not geographically aware**: matchday items are pinned to fixed windows relative to kickoff (arrival/fan-zone before, post-match after), and non-matchday items are distributed across the remaining days. This limitation is stated in the system prompt and surfaced in the itinerary's `assumptions` field, so the behavior is never overstated as true routing optimization.

Identical requests reuse a cached result without re-invoking the model, giving a second caching layer above the MCP middleware cache.

This ticket delivers the agent class and the two MCP tools only. No HTTP endpoint is built; wiring `/agents/itinerary/generate` is deferred to Phase 06-01, and that deferral is noted in the agent module.

## User Stories

1. As a traveler, I want a day-by-day itinerary for my trip dates, so that I can see a concrete plan rather than a flat list of places.
2. As a traveler, I want each itinerary item to have a start and end time, so that I know when to be where.
3. As a traveler, I want each item to include a short explanation, so that I understand why it was chosen for me.
4. As a traveler attending a match, I want matchday items anchored around kickoff (a fan zone or pub before, something after), so that the plan respects the single fixed point in my day.
5. As a budget-conscious traveler, I want recommendations filtered to my budget level, so that I am not sent to places I would not go.
6. As a traveler with specific interests (supporter pubs, nightlife, tourism), I want the itinerary biased toward those interests, so that the plan feels tailored.
7. As a traveler, I want to see the agent's confidence in the plan, so that I know how much to trust it.
8. As a traveler, I want to see the assumptions behind the plan — including that sequencing is matchday-anchored and not geographically optimized — so that I am not misled into thinking stops are arranged by travel distance.
9. As a traveler, I want to see why a budget level changed what was included, so that the budget input does not feel like a black box.
10. As a traveler whose city or match has thin data, I want a partial but clearly-marked itinerary, so that I still get value when seeded data is incomplete.
11. As a traveler making the same request twice, I want the same plan returned instantly, so that repeat requests are fast and cost nothing extra.
12. As a developer, I want the agent to never produce an itinerary item that was not in the gathered candidate set, so that the plan cannot reference hallucinated venues.
13. As a developer, I want the agent to never place more than the per-day item cap or items outside the requested date range, so that the structure stays valid and executable on foot.
14. As a developer, I want empty days allowed only when fewer candidates were genuinely ordered (not when the model silently forgot a day), so that empty days are intentional, not bugs.
15. As a developer, I want the agent to stop after at most four tool calls on Flash only, so that per-request cost stays bounded and predictable.
16. As a developer, I want approximate route context between key points (especially to and from the stadium) from seeded data, so that the agent can reason about sequence without any live routing API.
17. As a developer, I want `get_route_context` to degrade to static city transit guidance when a point-to-point pair is unknown, so that a missing route never breaks planning.
18. As a developer, I want `generate_itinerary` to degrade to a compact skeleton that preserves the supplied candidate order on timeout, so that formatting failures still return something usable.
19. As a developer, I want both new tools to follow the exact Phase 02 tool shape (seeded source, `external_api_called=false`, standard telemetry and error envelope), so that they integrate with the existing MCP server and middleware unchanged.
20. As a developer, I want telemetry emitted for tool calls, model calls, and agent completion, so that itinerary runs are observable like the other ADK agents.
21. As an operator, I want concurrent identical requests to invoke the model at most once, so that the cache actually controls cost under load instead of racing.

## Implementation Decisions

### Modules built or modified

- **`ItineraryADKAgent` (new agent module).** An ADK `LlmAgent` wrapper mirroring `MatchAnalystADKAgent` and `CityConciergeADKAgent`: Flash-only, no Pro path, no model routing. Constructor injects `stub_model`, `mcp_factory`, `settings`, and `metrics_writer` for testability. Enforces a 4-tool-call budget via a `before_tool_callback` backed by ADK session state; emits telemetry via `after_tool_callback`, model callbacks, and `AdkCallbackHooks`. Runs through `InMemoryRunner`. A top-of-module comment records the deferred HTTP wiring: `# HTTP: wired in Phase 06-01 via POST /agents/itinerary/generate`.
  - Public entry point: an async `generate(*, city_id, match_id, traveler_profile, start_date, end_date, session_id="")` method. `traveler_profile` is a dict carrying `party_size`, `interests`, `budget`, `accessibility_needs` (matching the contract input).
  - Returns a structured dict: `itinerary` (days → items), `reasoning`, `confidence` (label) and `confidence_details` (`{label, contributors, downgrade_reasons}`), `assumptions`, `degraded`, `degraded_reason`, `self_check`, `tool_sources`, `model_name`, `metrics`, and a `cache_hit` flag.
  - Tools available to the LLM (ReAct dispatch): `get_venues`, `get_city_events` (existing Phase 02), `get_route_context` (new), and `generate_itinerary` (new). System prompt instructs: gather candidates, optionally probe route context, filter by budget/interests, order candidates, then call `generate_itinerary` last with the ordered IDs. The prompt explicitly names sequencing as "matchday-anchored, not geographically optimized."

- **`generate_itinerary` MCP tool (new).** Pure deterministic formatter. Input per contract: `city_id`, `match_id`, `traveler_profile`, `ordered_candidate_ids`, `start_date`, `end_date`, `allow_external`. Maps the ordered candidate IDs onto days and time slots:
  - **Matchday anchoring:** items identified as matchday-relevant are pinned to fixed windows relative to kickoff — an arrival/fan-zone window before kickoff and a post-match window after. Kickoff is derived from the match's `started_at`/scheduled time. The stadium node used for anchoring is the stadium-typed venue candidate (e.g. `venue_bmo_field`), not `match_state.venue_id` (which is independently seeded and does not align).
  - **Non-matchday items** are distributed across the remaining days in supplied order, with fixed-duration slots.
  - Enforces caps: max 3 days, max 4 items per day. Overflow candidates are truncated.
  - Empty days are permitted only as a consequence of fewer ordered candidates — the formatter never fabricates filler items.
  - Echoes a per-item `explanation` and writes plan-level `assumptions`, including the matchday-anchored/no-geographic-awareness statement.
  - `source_type="seeded"`, `external_api_called=false`, `cacheable=True`, `max_retry_count=0`, `timeout_ms=2500`. Error codes: `INVALID_INPUT`, `MISSING_ORDERED_CANDIDATES`, `ITINERARY_GENERATION_FAILED`, `TIMEOUT`. Degraded path returns a compact skeleton preserving supplied order with `degraded_reason="ITINERARY_FORMATTING_TIMEOUT"`.

- **`get_route_context` MCP tool (new).** Returns approximate, backend-style route context between two known points from seeded data. Input per contract: `city_id`, `origin` (`{type, id}`), `destination` (`{type, id}`), `departure_time`, `mode`, `allow_external`. Allowed modes: `walk`, `transit`, `rideshare`, `drive`, `any`. Output: `estimated_duration_minutes`, `distance_km`, `route_summary`, `confidence`, `computed_at`, plus origin/destination/mode echo.
  - `source_type="seeded"`, `external_api_called=false`, `cacheable=True`, `max_retry_count=1`, `timeout_ms=1500`. Error codes: `INVALID_INPUT`, `ROUTE_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.
  - Lookup is **reverse-pair-tolerant** (forward miss falls back to the reversed pair). Seed concentrates on stadium-centric pairs (`venue_bmo_field` ↔ `venue_pub_1`, `venue_bmo_field` ↔ `venue_fanzone_1`).
  - On a full miss, degrades to static city-level transit guidance with `confidence="low"`, `degraded=True`, `degraded_reason="POINT_TO_POINT_ROUTE_UNAVAILABLE"`, and no precise duration claim.

- **`RouteContextRepository` / `InMemoryRouteContextRepository` (new, in the existing city-data repository module).** Holds the seeded pairwise route table keyed by `(origin_id, destination_id)` with per-mode duration/distance and a route summary, plus the static city-level fallback. Lives alongside the existing in-memory venue/event/profile repositories and follows the same `set_repository`-style injection pattern.

- **MCP schemas (modified).** Add `GenerateItineraryInput` and `RouteContextInput` (both extending the shared base input so they inherit `allow_external`), and `GenerateItineraryOutput` / `RouteContextOutput` aliased to the shared base response type, consistent with the existing tool schemas.

- **MCP server registration (modified).** Add both new tool modules' `DEFINITION`s to the server's tool module list so they register through the existing `build_mcp_server` path, inheriting validation, timeout, retry, caching, and telemetry middleware unchanged.

### Agent-side caching (second layer)

- An in-process cache persists across `generate()` calls, keyed by a stable hash of `(city_id, match_id, traveler_profile, start_date, end_date)` computed from sorted-JSON via a cryptographic digest.
- Cache lookup and the model run are guarded by an `asyncio.Lock` **keyed by the input hash**, so concurrent identical requests invoke the model at most once: the first populates the cache, the rest await and return the cached result.
- A cache hit returns the stored structured result with `cache_hit=True` and skips the LLM run entirely.
- This sits above the MCP middleware's per-tool cache (the platform's first layer).

### Sequencing and self-check

- **Sequencing ownership:** the LLM orders candidates; the tool formats. The tool never computes ordering from scratch (honoring the contract). The honest label "matchday-anchored, no geographic awareness" appears in the system prompt and the response `assumptions`.
- **Budget handling:** budget filtering is prompt-driven (the LLM filters candidates by `traveler_profile.budget`); the rationale (e.g. "filtered by budget=medium") is written into `assumptions` so budget influence is traceable.
- **Bounded self-check (deterministic, no re-prompt loop):**
  1. Every itinerary `item_id` exists in the gathered candidate set (no hallucinated venues).
  2. Every day falls within `start_date..end_date`.
  3. No day exceeds the per-day item cap (4).
  4. No unintentionally empty days — an empty day is allowed only when fewer candidates were ordered, not when the model skipped a populated day.
  - A failed check sets `degraded=True` with a specific reason; it never silently passes.

### Confidence

- Reuses the established `{label, contributors, downgrade_reasons}` shape. `high` when venue, event, and route context are all grounded and non-degraded; `medium` when partial; `low` when candidates are missing or any tool degraded.

### Cost rules

- Flash only; no Pro; no model routing/escalation. Max 4 tool calls per run. No live routing APIs — route context is approximate and seeded. Itinerary length capped (3 days × 4 items). Structured JSON output to minimize formatting retries.

## Testing Decisions

Good tests here exercise external behavior and contracts, not internal heuristics. Mirror the existing ADK agent tests (`test_match_analyst_adk_agent.py`): a `_StubLlm(BaseLlm)` scripts the ReAct sequence (gather candidates → order → call `generate_itinerary`) so no live model is invoked, and a `_MockMCP` injected via `mcp_factory` returns contract-shaped seeded payloads, preserving the tool boundary.

Agent-level coverage to call out:
- Itinerary is structured by day with timed items, reasoning, confidence, and assumptions present.
- Matchday item is anchored to the kickoff-relative window; non-matchday items distribute across remaining days.
- The `assumptions` field contains the matchday-anchored/no-geographic-awareness statement and the budget-filter rationale.
- Missing/thin data produces a partial, `degraded`-marked itinerary rather than an error.
- Self-check failures are caught: a hallucinated `item_id`, an out-of-range day, an over-cap day, and an unintentionally empty day each set `degraded` with a reason.
- Cache reuse: a second `generate()` with identical input returns the cached result and does **not** invoke the model.
- Concurrency: two concurrent identical `generate()` calls invoke the model at most once (lock keyed by input hash).
- Budget influence is reflected in `assumptions`.
- Tool-call budget: the agent stops at 4 tool calls.

Tool-level coverage (in the MCP tools test suite, alongside the Phase 02 tools):
- `generate_itinerary`: happy path (ordered IDs → day/time structure), caps enforced, `MISSING_ORDERED_CANDIDATES` on empty input, degraded skeleton preserving order on timeout, `source_type="seeded"` and `external_api_called=false`.
- `get_route_context`: happy path for a seeded stadium-centric pair, reverse-pair lookup, degraded static fallback with `POINT_TO_POINT_ROUTE_UNAVAILABLE` on an unknown pair, mode validation, and the standard error/telemetry envelope.
- Both tools register cleanly through `build_mcp_server` and pass schema validation.

## Out of Scope

- The HTTP endpoint `/itineraries/generate` (or `/agents/itinerary/generate`). No web layer is added in this ticket; it is deferred to Phase 06-01 and noted in the agent module.
- Real geographic routing or true sequence optimization. Routing is approximate, seeded, and matchday-anchored only.
- Live external APIs of any kind. All data is seeded; `external_api_called` is always false.
- Multi-city support and cities beyond the existing seeded set.
- A Pro model path, model routing, or escalation logic.
- Persistent/distributed caching, TTL eviction, and cache invalidation strategy beyond the in-process second-layer cache.
- Backfilling a real "backend preprocessing" sequencer; the LLM fills that role for this ticket.

## Further Notes

- **Contract vs. convention divergence:** the contract examples show `source_type="cached"` for both new tools; this PRD standardizes on `source_type="seeded"` to match Phase 02 conventions (`seeded` = curated dataset; `cached` = fetched-once-and-held). This is an intentional, documented deviation.
- **Seed inconsistency to respect:** `get_match_state` returns `venue_id="venue_456"`, which does not correspond to the seeded stadium node `venue_bmo_field`. The matchday anchor keys off the stadium-typed venue candidate from `get_venues`, not `match_state.venue_id`. Planning should not try to reconcile these two seeds.
- **Honesty over fake sophistication:** the matchday-anchored heuristic can still produce sequences that ignore travel time between non-stadium stops. This is acceptable for a seeded demo provided it is labeled as such in the prompt and `assumptions`. A future "right fix" — having the LLM emit time-anchored candidate windows that the tool validates and rejects when impossible — is noted as follow-up, not built here.
- **Concurrency footgun:** the agent-side cache must be lock-guarded per input hash from the start; an unguarded module-level dict would let concurrent identical requests each invoke the model, breaking the cost-control story under load.
- **Dependencies:** relies on the existing MCP server/middleware, Phase 02 `get_venues`/`get_city_events`, the in-memory city-data repository, and the shared ADK callback/metrics/runtime helpers. Single seeded city (`city_toronto`).
- **Open question for planning:** whether matchday-relevance of a candidate is determined by venue type (stadium/fan-zone tags) and event category, or passed explicitly by the agent in the ordered candidate payload. Recommended: infer from seeded venue/event metadata in the formatter to keep the agent contract simple.
