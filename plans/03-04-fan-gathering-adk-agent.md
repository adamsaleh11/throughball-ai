# Plan: Rebuild Fan Gathering Agent as ADK Agent

> Source PRD: docs/prds/03-04-fan-gathering-adk-agent.md

## Architectural decisions

- **Agent class**: `google.adk.agents.LlmAgent` — the execution primitive; replaces the hand-rolled `FanGatheringAgent` class
- **Model**: `Settings.gemini_flash_model` (default `"gemini-2.0-flash-001"`); smoke test targets `"gemini-2.5-flash"` — never Pro
- **MCP boundary**: tools are `FunctionTool` wrappers calling `mcp.call_tool()` — the 07-01 middleware (tracing, cache, retry, budget) is preserved
- **Session services**: ADK's `google.adk.sessions.InMemorySessionService` for the `InMemoryRunner`; project's `throughball_ai.adk.InMemorySessionService` (`AdkSession`) for the metrics accumulator — two separate concerns
- **Budget enforcement**: tool call counter in ADK session `state["tool_call_count"]` — per-session, async-safe; `RunConfig(max_llm_calls=settings.max_agent_iterations)` for iteration limit
- **Response contract**: adds `model_name` (str) and `metrics` (dict with `tool_call_count`, `total_latency_ms`, `tool_latencies`); retires `telemetry` top-level key — documented in `docs/contracts/`
- **Test strategy**: `_StubLlm` subclasses `BaseLlm`; `mcp_factory` injection for MCP mock — zero live API calls in CI
- **Answer safety**: 480-char cap (mobile chat bubble constraint); Python post-processor enforces "Cached matchday data suggests…" prefix and sweeps for banned freshness phrases

---

## Phase 1: Agent scaffold, MCP tool wiring, basic answer

**User stories**: 1, 5, 6, 7, 8, 9, 10, 27

### What to build

A `FanGatheringADKAgent` Python class wrapping an `LlmAgent` with the Flash model and three `FunctionTool` wrappers for `get_fan_hotspots`, `get_city_events`, and `get_venues`. Each tool wrapper calls through `mcp.call_tool()`. The `answer()` method creates an ADK session, runs the agent via `InMemoryRunner`, collects events, and returns a minimal response dict with `answer` text and `model_name`. Tests use `_StubLlm` (happy-path scenario) and `mcp_factory` injection.

### Acceptance criteria

- [ ] `FanGatheringADKAgent` accepts `stub_model`, `mcp_factory`, and `settings` for testability
- [ ] `answer()` returns a dict containing `answer` (non-empty string) and `model_name`
- [ ] `model_name` contains `"flash"` and does not contain `"pro"`
- [ ] `tool_sources` lists all three tools with correct tool names
- [ ] Answer length ≤ 480 characters
- [ ] `_StubLlm` happy-path test passes with no live API calls

---

## Phase 2: Tool call budget and iteration limit enforcement

**User stories**: 11, 12, 13, 24c, 24d

### What to build

Add a `before_tool_callback` that reads `state["tool_call_count"]` from the ADK callback context. If the count equals 3, the callback returns an error dict and blocks the call; otherwise it increments the counter via session state mutation. Add `RunConfig(max_llm_calls=settings.max_agent_iterations)` to each `run_async` call. Extend test coverage with EXCEED_CAP and NO_TOOLS stub scenarios.

### Acceptance criteria

- [ ] A 4th tool call is blocked by `before_tool_callback`; the run completes without raising
- [ ] NO_TOOLS scenario returns `degraded: true` and `confidence: "low"`
- [ ] Tool call counter is per-session (lives in ADK session state, not a closure)
- [ ] `RunConfig.max_llm_calls` is wired from `Settings.max_agent_iterations`

---

## Phase 3: Callbacks and metrics in response

**User stories**: 14, 15, 16, 20, 21, 22, 28

### What to build

Wire `AdkCallbackHooks` to ADK's native callback slots: `after_model_callback` → `hooks.on_model_completed(...)`, `after_tool_callback` → `hooks.on_tool_completed(...)`. After the runner event loop finishes, call `hooks.on_agent_completed(...)` once. Accumulate `tool_call_count`, `total_latency_ms`, and per-tool latencies into a `metrics` dict in the response. Remove the `telemetry` top-level key. Update `docs/contracts/` to document the new shape.

### Acceptance criteria

- [ ] Response contains `metrics` with `tool_call_count`, `total_latency_ms`, and `tool_latencies`
- [ ] `telemetry` top-level key is absent from the response
- [ ] `metrics.tool_call_count` equals 3 on happy path
- [ ] `docs/contracts/` updated in same PR to document the contract change

---

## Phase 4: Python post-processing and full safety enforcement

**User stories**: 2, 3, 4, 17, 18, 19, 23, 24a, 24b, 25

### What to build

Add two post-processors applied after the runner loop extracts the final answer text:
1. **Prefix enforcer**: if any tool result has `source_type` in `{"seeded", "cached"}` and the answer does not start with `"cached"` (case-insensitive), prepend `"Cached matchday data suggests "` and lowercase the first character of the original answer.
2. **Banned-phrase sweeper**: if any of `("currently", "right now", "live", "confirmed gathering", "are there now")` appear in the answer, set `degraded: true` and populate `degraded_reason` naming the offending phrase.

Assemble confidence, `evidence_summary`, `verified_signals`, `inferred_signals`, and `tool_sources` from tool result events using the existing deterministic logic (ported from `fan_gathering.py`). Cover the MISSING_TOOL stub scenario and the degraded MCP scenario.

### Acceptance criteria

- [ ] Seeded-source answers that lack the prefix have it injected by Python
- [ ] A banned freshness phrase in the answer sets `degraded: true` and populates `degraded_reason`
- [ ] `verified_signals` and `inferred_signals` are correctly extracted from hotspot data
- [ ] MISSING_TOOL scenario (2 of 3 tools called) returns a valid, non-crashing response
- [ ] Degraded MCP scenario (`get_city_events` throws) propagates `degraded: true` on the relevant tool source

---

## Phase 5: Smoke test and migration cleanup

**User stories**: 26, 29

### What to build

Add a `@pytest.mark.smoke` test that runs the agent against real Gemini Flash (excluded from CI with `-m "not smoke"`). Then delete `src/throughball_ai/agents/fan_gathering.py` and `tests/test_fan_gathering_agent.py`. Update `src/throughball_ai/agents/__init__.py` to remove `fan_gathering` from `AGENT_NAMES` if it references the old module; add any necessary exports for the new agent. Fix any remaining import references across the codebase.

### Acceptance criteria

- [ ] Smoke test passes against real Gemini Flash (model string confirmed in response)
- [ ] Old `fan_gathering.py` deleted
- [ ] Old `test_fan_gathering_agent.py` deleted
- [ ] No import in the codebase references the old `fan_gathering` module
- [ ] All unit tests pass after cleanup
