# PRD: ADK Callbacks and Tracing (08-02)

## Problem Statement

Every agent run in throughball-ai currently completes without emitting a structured, run-level telemetry record. The MCP tool layer already writes per-tool-call traces to a local JSONL file (`telemetry/traces.jsonl`), but the ADK agent layer has no equivalent. Operators have no way to see how much a run cost, how long each tool took, whether a run degraded, or what confidence the agent reached — without reading raw application logs. Additionally, the codebase has a duplicate model-call emission path (`telemetry/events.py`) that was scaffolded before `callbacks.py` existed and is now dead weight. The scaffolded `callbacks.py` is also missing several fields required for a complete run record (`session_id`, `final_confidence`, per-tool latency breakdown).

## Solution

Add a `RunMetricsAccumulator` to a new `telemetry/agent_metrics.py` module. This accumulator is instantiated at the start of each agent run, records tool-call latencies and model-call token/cost stats as the run progresses, and on completion emits a single structured JSON line to `telemetry/agent_runs.jsonl` containing every required metric. The existing `AdkCallbackHooks` in `callbacks.py` is extended to carry `session_id`, `final_confidence`, and `tool_latencies`. The dead `telemetry/events.py` module is deleted and its one test migrated. No paid tracing vendor, BigQuery, or full OpenTelemetry pipeline is introduced.

## User Stories

1. As an operator, I want every agent run to emit a single structured JSON record so that I can inspect cost, latency, and quality for any run without parsing unstructured logs.
2. As an operator, I want `cost_per_request` visible in each run record so that I can track spend per query over time.
3. As an operator, I want `tokens_per_second` computed and included whenever token count and latency data are both present so that I can detect model performance regressions.
4. As an operator, I want `tool_latencies` as a named dict (tool → total ms) so that I can identify which tool is the bottleneck in a slow run.
5. As an operator, I want `final_confidence` included in the run record so that I can correlate confidence labels with cost and tool outcomes.
6. As an operator, I want `degraded` flagged in the run record so that I can filter for runs where one or more tools fell back to degraded mode.
7. As an operator, I want `tool_call_count` and `retries` in the run record so that I can detect retry storms or unexpectedly high tool fan-out.
8. As a developer, I want individual tool calls to remain traceable via their existing per-event records in `traces.jsonl` so that I can drill from a run summary down to a specific tool span.
9. As a developer, I want the accumulator interface to be simple enough that wiring it into a new agent requires only a few lines so that adding telemetry to future agents is low-friction.
10. As a privacy-conscious operator, I want the run record to log only chunk IDs and source references — never full user prompts or retrieved document bodies — so that private user data does not appear in telemetry files.
11. As a developer, I want the `callbacks.py` hooks to accept `session_id` and `final_confidence` so that the full required field set is available to downstream consumers.
12. As a developer, I want `telemetry/events.py` and `TelemetryContext` removed so that there is one canonical path for emitting model-call events and no confusion about which to use.
13. As a developer, I want the existing `adk/metrics.py` (`build_llm_metrics`) retained as the pure computation layer used by both the callbacks and the accumulator so that cost and token math is not duplicated.
14. As an operator, I want the run record written to a local JSONL file by default so that the system works without any external service configured.
15. As a developer, I want the JSONL writer injectable so that a Supabase backend can be wired in later without touching accumulator logic.

## Implementation Decisions

**Modules to create:**
- `telemetry/agent_metrics.py` — contains `RunMetricsAccumulator`. Instantiated once per agent run. Exposes `record_tool_call(name: str, latency_ms: int)`, `record_model_call(usage: dict, latency_ms: int, model_name: str)`, and `finalize(final_confidence: str | None) -> dict`. On `finalize`, emits a complete run-summary event and returns it. The emitter is an injectable callable (default: append to `telemetry/agent_runs.jsonl`).

**Modules to modify:**
- `adk/callbacks.py` — add `session_id: str` to all three hook signatures. Add `final_confidence: str | None = None` and `tool_latencies: dict[str, int] = {}` to `on_agent_completed`. No structural change to `_base_event` or `_emit`.
- `agents/fan_gathering.py` — instantiate `RunMetricsAccumulator` at the start of `answer()`, call `record_tool_call` after each `_call_tool` resolves (recording per-tool wall time), call `finalize(final_confidence=confidence["label"])` at the end. Surface `agent_run_id` and `trace_id` into the return dict's `telemetry` block.
- `telemetry/__init__.py` — remove re-exports of `TelemetryContext` and `emit_model_call_completed`; add re-export of `RunMetricsAccumulator` from `agent_metrics`.
- `adk/__init__.py` — no change; `build_llm_metrics` stays exported.

**Modules to delete:**
- `telemetry/events.py` — duplicate of the callbacks path. Not called from any production source.

**ID generation:**
- `agent_run_id` generated via the existing `new_id("ar")` utility from `mcp/trace.py` at the start of `answer()`.
- `trace_id` generated via `new_id("tr")` when no upstream trace context is present.

**Run-summary event shape** (all fields required unless noted):
- `event_type`: `"agent_run_completed"`
- `event_version`: `"1.0"`
- `timestamp`: UTC ISO-8601
- `agent_run_id`, `session_id`, `trace_id`, `request_id`
- `model_name`, `agent_name`
- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `tokens_per_second`: `completion_tokens / (latency_ms / 1000)`, `0.0` if either is absent
- `estimated_cost`, `cost_per_request` (same value; `cost_per_request` is the user-facing alias)
- `tool_call_count`, `tool_latencies`: `{"tool_name": total_ms, ...}`
- `retries`, `degraded`
- `final_confidence`: optional string label (`"high"` / `"medium"` / `"low"` / `null`)
- `latency_ms`: total wall time for the full run

**Privacy constraints:**
- No prompt text, no retrieved document bodies in any telemetry event.
- Retrieval references log only `chunk_id` and `source_path` (mirrors existing `_RETRIEVAL_REF_KEYS` in `session_service.py`).

**Storage:**
- Default writer: append newline-delimited JSON to `telemetry/agent_runs.jsonl`, mirroring `mcp/trace.py`'s pattern for `telemetry/traces.jsonl`.
- Writer is an injectable callable on the accumulator constructor for future Supabase swap-in.

**Cost computation:**
- Delegated to `adk/metrics.py`'s `build_llm_metrics`, which calls `telemetry/costs.py`'s `estimate_model_cost`. No duplication.

## Testing Decisions

**What makes a good test here:** test the emitted event shape and field values against known inputs; do not test internal accumulator state. Mock the JSONL writer to avoid filesystem I/O. Use `caplog` to assert log output for callbacks, consistent with existing `test_adk_runtime.py` and `test_telemetry.py` patterns.

**Coverage required:**
- `RunMetricsAccumulator.finalize()` emits an event containing all required fields when given complete usage, tool records, and a confidence label.
- `tokens_per_second` is `0.0` when `latency_ms` is 0 or `completion_tokens` is 0; correct float otherwise.
- `tool_latencies` aggregates correctly when the same tool is called multiple times.
- `degraded` is `True` in the summary when any recorded tool call was marked degraded.
- `AdkCallbackHooks.on_agent_completed` includes `session_id` and `final_confidence` in the emitted event.
- Deleting `telemetry/events.py` does not break any remaining test — `test_telemetry.py` migrated to `AdkCallbackHooks`.
- Privacy: no field in the emitted event contains a string longer than a reference (spot-check that `chunk_id` / `source_path` keys are present but raw document text is absent).

**Prior art:**
- `tests/test_adk_runtime.py` — `AdkCallbackHooks` and `build_llm_metrics` tests, use as the pattern for new accumulator tests.
- `tests/mcp/test_trace.py` — JSONL emission tests with injected writer, use as the pattern for the agent_runs writer.

## Out of Scope

- Supabase writer implementation (interface only; wiring left for a future ticket).
- Full OpenTelemetry pipeline or any paid tracing vendor.
- BigQuery export.
- Per-session aggregation across multiple runs.
- Prompt token logging or user query storage.
- Metrics for the `GeminiFlashSynthesisAdapter` live inference path (no token usage is returned in the current stub; add when live inference is wired).

## Further Notes

- `telemetry/traces.jsonl` (MCP tool-level) and `telemetry/agent_runs.jsonl` (agent run-level) are intentionally separate files. The run record links to tool spans via `trace_id` and `agent_run_id`; consumers join them externally.
- Supabase is already installed in the venv. When the Supabase writer is implemented, the table schema should match the run-summary event shape exactly so the JSONL format can serve as the migration source.
- The `estimate_model_cost` table in `telemetry/costs.py` covers only Gemini Flash/Pro variants. If the model router selects an unknown model, cost falls back to `0.0` with `estimator_version = "unknown-model-v1"` — this is already handled and acceptable.
- `session_id` on the accumulator should come from `InMemorySessionService.create_session()`. When the fan gathering agent is not using a managed session (current state), generate a synthetic session ID via `new_id("sess")` for the duration of the run.
