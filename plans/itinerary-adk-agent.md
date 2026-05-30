# Plan: Itinerary ADK Agent (03-07)

> Source PRD: `docs/prds/03-07-itinerary-adk-agent.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Surface**: Agent class + two MCP tools only. No HTTP endpoint — deferred to Phase 06-01 (`POST /agents/itinerary/generate`), noted in the agent module.
- **MCP tool shape**: Both new tools follow Phase 02 conventions exactly — standard `{ok, tool, source_type, data, telemetry}` envelope, `error_response` helper for errors, registered via the existing `build_mcp_server` tool-module list, validated through existing middleware. `source_type="seeded"`, `external_api_called=false` always (intentional deviation from the contract examples' `"cached"`).
- **`generate_itinerary`**: pure deterministic formatter. Input `{city_id, match_id, traveler_profile, ordered_candidate_ids, start_date, end_date, allow_external}`. `cacheable=True`, `max_retry_count=0`, `timeout_ms=2500`. Errors: `INVALID_INPUT`, `MISSING_ORDERED_CANDIDATES`, `ITINERARY_GENERATION_FAILED`, `TIMEOUT`. Caps: max 3 days, max 4 items/day.
- **`get_route_context`**: seeded approximate routing. Input `{city_id, origin{type,id}, destination{type,id}, departure_time, mode, allow_external}`; modes `walk|transit|rideshare|drive|any`. Output `{estimated_duration_minutes, distance_km, route_summary, confidence, computed_at, origin_id, destination_id, mode}`. `cacheable=True`, `max_retry_count=1`, `timeout_ms=1500`. Errors: `INVALID_INPUT`, `ROUTE_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`. Reverse-pair-tolerant lookup; degraded static fallback `POINT_TO_POINT_ROUTE_UNAVAILABLE`, `confidence="low"`.
- **Seed**: single city `city_toronto`; route table keyed `(origin_id, destination_id)`, stadium-centric pairs (`venue_bmo_field` ↔ `venue_pub_1`/`venue_fanzone_1`). Repository lives in the existing city-data repo module beside the venue/event/profile repositories.
- **Sequencing**: LLM owns ordering; the tool formats only. Matchday-anchored (kickoff-relative windows), **not** geographically optimized — labeled honestly in the system prompt and the response `assumptions`. Matchday-relevance inferred from seeded venue type / event category inside the formatter.
- **Match anchor**: kickoff derived from match `started_at`; stadium anchor is the stadium-typed venue candidate (`venue_bmo_field`), **not** `get_match_state.venue_id` (`venue_456`, an unreconciled seed).
- **Agent**: `ItineraryADKAgent`, ADK `LlmAgent` wrapper mirroring `match_analyst_adk.py`. Flash-only, no Pro/routing. 4 tool-call budget via `before_tool_callback` + ADK session state. Telemetry via `after_tool_callback`, model callbacks, `AdkCallbackHooks`. `InMemoryRunner`. Constructor injects `stub_model`, `mcp_factory`, `settings`, `metrics_writer`.
- **Agent entry point**: `async generate(*, city_id, match_id, traveler_profile, start_date, end_date, session_id="")`. Returns `{itinerary, reasoning, confidence, confidence_details, assumptions, degraded, degraded_reason, self_check, tool_sources, model_name, metrics, cache_hit}`.
- **Confidence**: reuse `{label, contributors, downgrade_reasons}` shape. high = venues+events+route grounded & non-degraded; medium = partial; low = candidates missing or any tool degraded.
- **Budget**: prompt-driven filtering; rationale written into `assumptions`.
- **Second-layer cache**: in-process, persists across `generate()` calls, keyed by sha256 of sorted-JSON `(city_id, match_id, traveler_profile, start_date, end_date)`. Guarded by `asyncio.Lock` per input hash. Hit returns stored result with `cache_hit=True`, skipping the LLM. Sits above the MCP middleware cache.
- **Testing**: `_StubLlm(BaseLlm)` scripts ReAct; `_MockMCP` injected via `mcp_factory` returns contract-shaped seeded payloads. Tool tests live alongside the Phase 02 tool suite.

---

## Phase 1: `get_route_context` MCP tool (seeded, end-to-end)

**User stories**: 16, 17, 19

### What to build

A new MCP tool returning approximate route context between two seeded points, fully wired through the existing MCP server. Add a `RouteContextRepository` + `InMemoryRouteContextRepository` to the city-data repository with a stadium-centric seed table, reverse-pair-tolerant lookup, and a static city-level fallback. Add input/output schemas, register the tool in the server's module list, and emit the standard telemetry envelope. Unknown point-to-point pairs degrade to static transit guidance rather than erroring.

### Acceptance criteria

- [ ] Calling the tool with a seeded stadium-centric pair returns `estimated_duration_minutes`, `distance_km`, `route_summary`, `confidence`, `computed_at`, with `source_type="seeded"` and `external_api_called=false`.
- [ ] A reversed pair (destination↔origin of a seeded entry) resolves to the same route.
- [ ] An unknown pair returns a degraded static city-transit response: `degraded=true`, `degraded_reason="POINT_TO_POINT_ROUTE_UNAVAILABLE"`, `confidence="low"`, no precise duration claim.
- [ ] Invalid input (missing origin/destination/city) returns `INVALID_INPUT`; an invalid `mode` is rejected.
- [ ] The tool registers and validates cleanly through `build_mcp_server` and is callable on the server.

---

## Phase 2: `generate_itinerary` pure formatter (seeded, end-to-end)

**User stories**: 1, 2, 3, 4, 13, 14, 18, 19

### What to build

A new MCP tool that deterministically formats an ordered list of candidate IDs into a day-by-day itinerary. Matchday-relevant candidates are pinned to kickoff-relative windows (anchored on the stadium-typed candidate); the rest distribute across remaining days in supplied order with fixed-duration slots. Enforces the 3-day / 4-item caps, allows empty days only as a consequence of fewer candidates, attaches per-item explanations, and writes plan-level `assumptions` including the matchday-anchored / no-geographic-awareness statement. Degrades to a compact order-preserving skeleton on timeout.

### Acceptance criteria

- [ ] Supplied `ordered_candidate_ids` produce days with timed items (`start_time`, `end_time`, `item_type`, `item_id`, `title`, `explanation`), `source_type="seeded"`, `external_api_called=false`.
- [ ] A matchday candidate is placed in a kickoff-relative window (before/after kickoff) anchored on the stadium candidate, not `match_state.venue_id`.
- [ ] Caps enforced: never more than 3 days or 4 items/day; overflow truncated.
- [ ] Empty candidate list returns `MISSING_ORDERED_CANDIDATES`; empty days appear only when fewer candidates were ordered (no fabricated filler).
- [ ] `assumptions` contains the matchday-anchored / no-geographic-awareness statement.
- [ ] Timeout path returns a compact skeleton preserving supplied order with `degraded_reason="ITINERARY_FORMATTING_TIMEOUT"`.
- [ ] Registers and validates cleanly through `build_mcp_server`.

---

## Phase 3: `ItineraryADKAgent` thin slice (ReAct, Flash, budget)

**User stories**: 5, 6, 7, 15, 20

### What to build

A minimal ADK agent wrapping the four tools (`get_venues`, `get_city_events`, `get_route_context`, `generate_itinerary`), mirroring `match_analyst_adk.py`. The LLM (stubbed in tests) gathers candidates, optionally probes route context, orders candidates by interest/budget, and calls `generate_itinerary` last. Enforces the 4 tool-call budget, emits tool/model/agent telemetry, and returns the structured result (`itinerary`, `reasoning`, `confidence`, `confidence_details`, `tool_sources`, `model_name`, `metrics`). First demoable full agent run.

### Acceptance criteria

- [ ] `generate(...)` with a stubbed LLM scripting gather→order→`generate_itinerary` returns a structured itinerary with reasoning and a confidence label.
- [ ] The agent stops after at most 4 tool calls; a 5th attempt is blocked by the budget callback.
- [ ] Runs Flash-only (no Pro/model-routing path exists).
- [ ] Tool, model, and agent-completion telemetry are emitted via the callback hooks.
- [ ] No live model or MCP call occurs in tests (`_StubLlm` + `_MockMCP` via `mcp_factory`).

---

## Phase 4: Bounded self-check, confidence & honest assumptions

**User stories**: 8, 9, 10, 12, 13, 14

### What to build

Harden the agent against realistic LLM failures with a deterministic, no-re-prompt self-check and finalize confidence/degraded reporting. The self-check verifies item existence, date range, per-day cap, and intentional-empty-day rules; failures mark `degraded` with a specific reason. Confidence is computed from grounding/degradation. The `assumptions` field surfaces both the matchday-anchored honesty statement and the budget-filter rationale. Thin/missing data yields a partial, clearly-marked itinerary instead of an error.

### Acceptance criteria

- [ ] A hallucinated `item_id` (not in gathered candidates) sets `degraded=true` with a reason.
- [ ] An out-of-range day, an over-cap day, and an unintentionally empty day each fail the self-check with a specific reason.
- [ ] An intentional empty day (fewer candidates ordered) passes the self-check.
- [ ] Confidence is `high` only when venues+events+route are grounded and non-degraded; `low` when candidates missing or any tool degraded.
- [ ] `assumptions` includes the matchday-anchored statement and a budget-filter rationale (e.g. budget level applied).
- [ ] Thin-data input returns a partial itinerary with `degraded=true`, not an exception.

---

## Phase 5: Second-layer cache (lock-guarded)

**User stories**: 11, 21

### What to build

An in-process agent-side cache persisting across `generate()` calls, keyed by a sha256 of sorted-JSON `(city_id, match_id, traveler_profile, start_date, end_date)`. Cache lookup + model run are guarded by an `asyncio.Lock` keyed by the input hash so concurrent identical requests invoke the model at most once. A hit returns the stored structured result with `cache_hit=True` and skips the LLM entirely.

### Acceptance criteria

- [ ] A second `generate()` with identical input returns the same result with `cache_hit=true` and does not invoke the stubbed model a second time.
- [ ] A different input (any keyed field changed) misses the cache and invokes the model.
- [ ] Two concurrent identical `generate()` calls invoke the model at most once; both receive the same result.
- [ ] The first response carries `cache_hit=false`.
