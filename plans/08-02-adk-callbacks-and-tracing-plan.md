# Plan: ADK Callbacks and Tracing

> Source PRD: plans/08-02-adk-callbacks-and-tracing.md

## Architectural decisions

- **Emission format**: Newline-delimited JSON (JSONL), compact (`separators=(",",":")`, `sort_keys=True`)
- **Local storage**: `telemetry/agent_runs.jsonl` for run summaries; `telemetry/traces.jsonl` for per-tool spans (existing)
- **ID generation**: `new_id("ar")` for `agent_run_id`, `new_id("tr")` for `trace_id`, `new_id("sess")` for synthetic session IDs — all from `mcp/trace.py`
- **Cost computation**: Delegated entirely to `adk/metrics.py` (`build_llm_metrics`) → `telemetry/costs.py` (`estimate_model_cost`). No duplication.
- **Privacy**: No prompt text, no retrieved document bodies in any emitted event. Retrieval refs log only `chunk_id` and `source_path`.
- **External services**: No paid vendor, no BigQuery, no OpenTelemetry pipeline. JSONL writer is injectable for future Supabase swap-in.
- **`tokens_per_second`**: `completion_tokens / (latency_ms / 1000)`, `0.0` if either is zero.
- **`tool_latencies`**: `dict[str, int]` — tool name → cumulative latency ms (summed if tool called multiple times).

---

## Phase 1: Remove duplicate emission path

**User stories**: #12 (remove `telemetry/events.py`), #13 (retain `build_llm_metrics`)

### What to build

Delete `telemetry/events.py` and the `TelemetryContext` dataclass. Update `telemetry/__init__.py` to remove those re-exports. Migrate the single test in `test_telemetry.py` to use `AdkCallbackHooks.on_model_completed` directly. Test suite stays fully green after the deletion.

### Acceptance criteria

- [ ] `telemetry/events.py` is deleted
- [ ] `telemetry/__init__.py` no longer exports `TelemetryContext` or `emit_model_call_completed`
- [ ] `test_telemetry.py` is migrated to `AdkCallbackHooks` and passes
- [ ] `adk/metrics.py` (`build_llm_metrics`) is untouched and still exported from `adk/__init__.py`
- [ ] All existing tests pass

---

## Phase 2: Extend callback hook contracts

**User stories**: #11 (`session_id` + `final_confidence` on hooks)

### What to build

Add `session_id: str` to all three `AdkCallbackHooks` method signatures and to `_base_event`. Add `final_confidence: str | None = None` and `tool_latencies: dict[str, int]` (default empty) to `on_agent_completed`. Update existing tests in `test_adk_runtime.py` to pass `session_id`. The emitted JSON for `agent_run_completed` events now includes `session_id`, `final_confidence`, and `tool_latencies`.

### Acceptance criteria

- [ ] All three hook methods accept and forward `session_id`
- [ ] `on_agent_completed` accepts `final_confidence` and `tool_latencies` and includes them in the emitted event
- [ ] `_base_event` includes `session_id` in its output dict
- [ ] Existing `test_adk_runtime.py` tests updated and passing with `session_id` present
- [ ] New test asserts `session_id`, `final_confidence`, and `tool_latencies` appear in an `agent_run_completed` event

---

## Phase 3: Build RunMetricsAccumulator

**User stories**: #1–10, #14, #15

### What to build

Create `telemetry/agent_metrics.py` containing `RunMetricsAccumulator`. The accumulator is constructed with `agent_run_id`, `session_id`, `trace_id`, `request_id`, `agent_name`, and an optional injectable writer callable (default: append to `telemetry/agent_runs.jsonl`). It exposes:

- `record_tool_call(name, latency_ms, degraded=False)` — accumulates per-tool latency and degraded flag
- `record_model_call(usage, latency_ms, model_name)` — accumulates token counts and cost via `build_llm_metrics`
- `finalize(final_confidence=None) -> dict` — computes the complete run-summary event and calls the writer

The emitted event contains every field in the PRD's required field set. Update `telemetry/__init__.py` to export `RunMetricsAccumulator`.

### Acceptance criteria

- [ ] `finalize()` emits an event containing all required fields: `agent_run_id`, `session_id`, `trace_id`, `model_name`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `tokens_per_second`, `estimated_cost`, `cost_per_request`, `tool_call_count`, `tool_latencies`, `retries`, `degraded`, `final_confidence`
- [ ] `tokens_per_second` is `0.0` when `latency_ms=0` or `completion_tokens=0`; correct float otherwise
- [ ] `tool_latencies` sums correctly when the same tool is called multiple times
- [ ] `degraded` is `True` in the summary when any recorded tool call was marked degraded
- [ ] `cost_per_request` equals `estimated_cost`
- [ ] Unknown model produces `estimated_cost=0.0` without raising
- [ ] The injectable writer receives the event dict; default writer appends a JSONL line
- [ ] No field in the emitted event contains raw prompt text or retrieved document body
- [ ] `RunMetricsAccumulator` is importable from `telemetry`

---

## Phase 4: Wire accumulator into FanGatheringAgent

**User stories**: #1–8, #10 (end-to-end run record from the real agent)

### What to build

Instantiate `RunMetricsAccumulator` at the top of `FanGatheringAgent.answer()` using `new_id` for `agent_run_id` and `trace_id`. After each `_call_tool` resolves, call `record_tool_call` with the tool name and wall-clock latency. Call `finalize(final_confidence=confidence["label"])` before returning. Surface `agent_run_id` and `trace_id` in the return dict's `telemetry` block alongside the existing fields. The accumulator writer is injectable so tests avoid filesystem I/O.

### Acceptance criteria

- [ ] `answer()` emits a run-summary event on every call (happy path and degraded path)
- [ ] The emitted event's `tool_call_count` matches the number of tools called
- [ ] `tool_latencies` keys match the tool names called (`get_fan_hotspots`, `get_city_events`, `get_venues`)
- [ ] `final_confidence` in the event matches the confidence label in the return dict
- [ ] `degraded` in the event is `True` when any tool result was degraded
- [ ] `agent_run_id` and `trace_id` appear in the return dict's `telemetry` block
- [ ] The accumulator writer is injected in tests (no real file written during test runs)
- [ ] All existing `test_fan_gathering_agent.py` tests continue to pass
