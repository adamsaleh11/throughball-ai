# Plan: City Concierge ADK Agent

> Source PRD: docs/prds/03-05-city-concierge-adk-agent.md

## Architectural decisions

Durable decisions that apply across all phases:

- **Agent class**: `google.adk.agents.LlmAgent` — execution primitive, same pattern as FanGatheringADKAgent
- **Model**: `Settings.gemini_flash_model` (default `"gemini-2.0-flash-001"`); never Pro
- **Tool budget**: 4 max, enforced via before_tool_callback in ADK session state
- **Session state**: ADK's InMemorySessionService + project's InMemorySessionService for metrics
- **Response contract**: `{ answer, confidence, citations, grounded, tool_sources, recommendations, model_name, metrics }`
- **Safety**: Banned phrases + citation validation + confidence heuristic (Python post-processor, no extra LLM call)
- **Retrieval**: RagAnsweringService (09-01) via search_documents tool; max 5 chunks per search
- **Metrics**: RunMetricsAccumulator (08-02) emits to telemetry/agent_runs.jsonl with tokens_per_second + cost_per_request
- **Session lifecycle**: Per-turn tool_call_count reset, per-session retrieval dedup cache
- **MCP boundary**: Tools are FunctionTool wrappers calling mcp.call_tool()

---

## Phase 1: Agent scaffold, tool wiring, basic answer

**User stories**: 5, 6, 9, 26

### What to build

A `CityConciergeADKAgent` Python class wrapping an `LlmAgent` with the Flash model and four `FunctionTool` wrappers for `get_city_profile`, `get_venues`, `get_city_events`, and `search_documents`. Each tool wrapper calls through `mcp.call_tool()`. The `answer()` method creates an ADK session, runs the agent via `InMemoryRunner`, collects events, and returns a response dict with `answer` text, `model_name`, and basic `metrics`.

System instruction guides the LLM to call tools strategically and cite sources.

### Acceptance criteria

- [ ] `CityConciergeADKAgent` accepts `stub_model`, `mcp_factory`, `settings` for testability
- [ ] `answer()` async method accepts `query`, `session_id`, `city_id`, [optional `team_id`]
- [ ] `answer()` returns a dict containing `answer` (non-empty string), `model_name`, and `tool_sources`
- [ ] `model_name` contains `"flash"` and does not contain `"pro"`
- [ ] `tool_sources` lists all four tools with correct tool names
- [ ] LLM can call all 4 tools; agent completes without hanging
- [ ] `_StubLlm` happy-path test passes with no live API calls
- [ ] Response includes basic `metrics` dict with `tool_call_count`

---

## Phase 2: Tool call budget enforcement and graceful degradation

**User stories**: 20, 21, 23, 24

### What to build

Add a `before_tool_callback` that reads `state["tool_call_count"]` from the ADK callback context. If the count equals 4, the callback returns an error dict and blocks the call; otherwise it increments the counter. Add individual tool failure handling (each tool returns a degraded_tool_result on exception). Set `degraded=true` flag in response when any tool fails, returns empty, or budget is exceeded.

### Acceptance criteria

- [ ] A 5th tool call is blocked; the run completes without raising
- [ ] Tool failure (exception) returns `{ error: "...", degraded: true }`
- [ ] Empty tool result (zero venues, zero events) is handled gracefully
- [ ] Response includes `degraded` boolean flag
- [ ] When any tool fails, `degraded=true` in final response
- [ ] Tool call counter is per-session (lives in ADK session state, not closure)
- [ ] Answer is still returned (partial) when degradation occurs

---

## Phase 3: Safety post-processing and confidence computation

**User stories**: 12, 13, 15, 22

### What to build

Implement post-processor functions:
1. **Banned phrase sweeper**: if "currently", "right now", "live", "confirmed gathering", "are there now" appear in answer, set `degraded=true` and populate `degraded_reason`.
2. **Citation validator**: extract all `[N]` markers from answer; if none found, set `grounded=false` and lower confidence.
3. **Confidence scorer**: heuristic based on retrieval_confidence + citations_found + tool_diversity; label as "high", "medium", or "low".
4. **Fallback answer**: when `grounded=false`, return fixed safe string: "I don't have enough reliable information to answer that. Try a more specific question, or consult official sources."

Extract citation metadata from tool results (source_path, title).

### Acceptance criteria

- [ ] Banned phrase in answer sets `degraded=true` and `degraded_reason` names the phrase
- [ ] Answer with no `[N]` citations sets `grounded=false` and confidence ≤ "medium"
- [ ] Confidence = "high" when retrieval_confidence="high" AND citations present AND ≥2 tools called
- [ ] Confidence = "low" when no chunks retrieved or no citations
- [ ] `citations` list populated with `{ id, source_path, title }` for each `[N]` marker
- [ ] Fallback answer used when `grounded=false`; all fields present in response

---

## Phase 4: Metrics accumulation and telemetry emission

**User stories**: 14, 24

### What to build

Wire `RunMetricsAccumulator` (from telemetry/agent_metrics.py, built in 08-02) into the agent. Capture tool call latencies and model usage (prompt/completion tokens). After the runner finishes, call `accumulator.finalize(final_confidence=confidence["label"])` to emit the run-completed event to telemetry/agent_runs.jsonl.

Compute `tokens_per_second` = completion_tokens / (latency_ms / 1000). Compute `cost_per_request` from estimate_model_cost(prompt_tokens, completion_tokens, model_name).

### Acceptance criteria

- [ ] Response contains `metrics` with `tool_call_count`, `total_latency_ms`, `tool_latencies`
- [ ] `metrics.tool_call_count` matches actual tools called
- [ ] `tool_latencies` is a dict mapping tool name to milliseconds (e.g., `{ "get_city_profile": 145 }`)
- [ ] `tokens_per_second` computed correctly (non-zero when tokens and latency present)
- [ ] `cost_per_request` estimated and included in metrics
- [ ] Agent run event emitted to telemetry/agent_runs.jsonl with all required fields
- [ ] No prompt/completion tokens logged (privacy: only metrics, not sensitive data)

---

## Phase 5: Multi-turn session support and context preservation

**User stories**: 8, 16, 17, 18, 19

### What to build

Integrate with `RagAnsweringService` for session-aware retrieval dedup. When `search_documents` is called, it uses `(session_id, normalized_query)` to check the cache; on cache hit, return cached chunks without re-embedding.

Extract user context from query on first turn (budget, dietary, interests, time constraints); append extracted context to system instruction on follow-ups. Log previous recommendations; append to prompt context on follow-ups so the agent remembers prior suggestions.

Tool call counter resets per turn (fresh 4-call budget).

### Acceptance criteria

- [ ] Same query twice in same session triggers `RetrievalService` only once (verify via call count)
- [ ] Different queries in same session are not deduplicated
- [ ] User preferences extracted once (Turn 1) and reused in Turn 2+ system prompt
- [ ] Previous recommendations appended to context on follow-ups
- [ ] Tool call counter resets to 0 at start of each turn
- [ ] Different session_ids maintain independent caches
- [ ] Follow-up turn completes with fresh 4-call budget

---

## Phase 6: Integration, context adaptation, and smoke test

**User stories**: 1, 2, 3, 4, 7, 10, 11, 25, 27, 28

### What to build

Refine system instruction to guide context extraction:
- Parse budget constraints ("€50", "max €100")
- Extract dietary preferences ("vegetarian", "vegan", "gluten-free")
- Extract interests ("art", "nightlife", "food")
- Extract time constraints ("2 hours", "3 days")

Implement recommendation balancing: for broad queries, aim for 1-2 items from each of 5 categories (restaurants, nightlife, tourism, fan events, local gems). For specific queries, prioritize requested category.

Wire agent into REST API endpoint or chat interface. Add optional smoke test (marked `@pytest.mark.smoke`, excluded from CI by default) that runs against real Gemini Flash.

### Acceptance criteria

- [ ] System instruction includes guidance on context extraction
- [ ] Agent extracts budget, dietary, interests, time from prose query
- [ ] Broad query ("What should I do?") yields mix across 5 categories
- [ ] Specific query ("Restaurants") prioritizes restaurants while mentioning other categories if relevant
- [ ] Response includes `recommendations` list with `{ category, items, reasoning }`
- [ ] Agent callable from REST endpoint (or chat interface) with proper error handling
- [ ] Smoke test runs against real Gemini Flash (if credentials available); marked `skip` in CI
- [ ] Answer time is < 1 second (user stories 27, 28)

