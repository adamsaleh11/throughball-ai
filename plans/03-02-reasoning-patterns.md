# PRD: ReAct Reasoning Patterns for FanGatheringAgent

## Problem Statement

The `FanGatheringAgent` currently produces answers through fully deterministic Python logic — it calls three tools in parallel, runs a rule-based confidence calculator, and synthesizes a canned text answer. There is no visible reasoning step, no LLM-generated plan, and no check that the final answer is grounded in the data that was actually returned. This makes the agent opaque, difficult to audit, and leaves no trace of *why* a particular answer was chosen. It also means the agent has no interface by which a parent coordinator can delegate work to it in Phase 04.

## Solution

Introduce a single-cycle ReAct pattern into `FanGatheringAgent`: a Flash LLM generates a brief reasoning plan before tools are dispatched, the same three tools are called in parallel, and a Flash LLM synthesizes the final answer from the plan and tool observations. A deterministic groundedness self-check runs once on the synthesized answer before it is returned, ensuring the answer does not make live-confirmation claims when the underlying data is seeded or cached. A parent-coordinator Protocol is added to the orchestration layer as a stub, wiring up the delegation interface that Phase 04 will implement. All reasoning steps are emitted to the existing JSONL trace system so that plan, tools used, confidence, and final answer are observable in logs.

## User Stories

1. As an API consumer, I want the agent's answer to reflect a reasoned plan, so that I can trust it considered what data sources were relevant before answering.
2. As an API consumer, I want the agent's confidence score to remain deterministic, so that the same tool results always produce the same confidence label regardless of LLM variance.
3. As an API consumer, I want the final answer to pass a groundedness check, so that the agent never claims fans are "currently gathering" when the data is seeded rather than live.
4. As an API consumer, I want the agent to return a `self_check_passed` field, so that downstream systems can decide whether to surface or suppress the answer based on groundedness.
5. As an operator reviewing logs, I want to see a `plan` field in the trace alongside `tools_used`, `confidence`, and `final_answer`, so that I can audit the full reasoning chain for any request.
6. As an operator, I want the reasoning step's LLM call to be tracked in `agent_run_completed` (tokens, latency, cost), so that I can measure the added cost of the ReAct cycle.
7. As an operator, I want the self-check result included in `agent_run_completed`, so that I can monitor what fraction of answers are failing groundedness over time.
8. As a Phase 04 developer, I want an `AgentCoordinator` Protocol available in the orchestration module, so that I can implement a parent coordinator that delegates to `FanGatheringAgent` without touching its internals.
9. As a Phase 04 developer, I want `FanGatheringAgent` to accept an optional `coordinator` argument, so that the Phase 04 wiring requires no changes to the agent's constructor signature.
10. As a test author, I want to inject mock LLM adapters for both the plan and synthesis steps, so that tests run fast and deterministically without live Vertex AI calls.
11. As a test author, I want the LLM self-check path to be skippable via a constructor flag, so that I can test groundedness logic separately from LLM integration.
12. As a developer, I want the three tool calls to remain in parallel and always fired, so that latency and cost are not increased by the planning step.
13. As a developer, I want the deterministic confidence calculator to remain unchanged, so that reasoning patterns do not alter the existing acceptance criteria for confidence labels.
14. As a developer, I want the agent to degrade gracefully when the plan LLM call fails, so that a Flash outage does not prevent answers from being returned (fall back to a canned plan string and continue).
15. As a developer, I want the synthesis LLM call to also degrade gracefully, so that a Flash synthesis failure falls back to the existing deterministic synthesizer rather than returning an error.

## Implementation Decisions

### Modules modified

**`FanGatheringAgent` (agents layer)**
- Constructor gains two injectable adapter arguments: one for the plan step (Flash LLM call that produces a `thought` string) and one for the synthesis step (Flash LLM call that produces the final answer string). Both default to real Flash adapters in production and accept mocks in tests.
- Constructor gains an optional `coordinator` argument typed as `AgentCoordinator | None`, stored but never called yet.
- Constructor gains a boolean `llm_self_check` flag (default `False`) that opts into an LLM-based self-check instead of the deterministic one.
- The `answer()` method is restructured into four sequential phases: **Plan**, **Act**, **Observe**, **Answer+Check**.
  - *Plan*: call the plan adapter with the request context, receive a `thought` string. On failure, use `"Calling get_fan_hotspots, get_city_events, and get_venues to answer the question."` as a fallback.
  - *Act*: call the three tools in parallel (unchanged).
  - *Observe*: normalize results, run the deterministic confidence calculator (unchanged).
  - *Answer*: call the synthesis adapter with the thought + tool observations. On failure, fall back to the existing deterministic `_synthesize_answer`. Then run the self-check.
- `_synthesize_answer` is kept as the fallback path, not removed.

**Plan adapter interface**
- A simple callable protocol: receives `(request: FanGatheringRequest, tool_names: list[str]) -> str` and returns the thought string.
- Default implementation calls Flash with a short prompt listing the question and available tools.

**Synthesis adapter interface**
- An extended version of the existing `GeminiFlashSynthesisAdapter`. Receives `(thought: str, tool_results: list[dict], confidence: dict, max_chars: int) -> str` and returns the answer string.
- Default implementation calls Flash. Tests inject a mock.

**Groundedness self-check (`_groundedness_check`)**
- A pure function: `(answer: str, tool_results: list[dict]) -> dict` returning `{"passed": bool, "reason": str}`.
- Deterministic rule: if any tool result has `source_type` in `{"seeded", "cached"}` and the answer contains any banned freshness phrase (`"currently"`, `"right now"`, `"live"`, `"confirmed gathering"`, `"are there now"`), the check fails.
- If `llm_self_check=True` and the deterministic check passes, an optional LLM pass runs using Flash. This path is never invoked in tests.
- The result is attached to the agent response as `self_check` and to the `agent_run_completed` event as `self_check_passed`.

**`AgentCoordinator` Protocol (`orchestrator` module)**
- A `Protocol` with a single async method: `delegate(agent_name: str, request: dict) -> dict`.
- No implementation — Phase 04 provides a concrete class.
- `FanGatheringAgent` stores the coordinator but never calls it until Phase 04.

**Trace system (existing `mcp/trace.py` + `telemetry/agent_metrics.py`)**
- A new trace event type `agent_reasoning_step` is emitted after the Plan phase completes, containing: `plan` (the thought string), `tools_used` (the three tool names), `fallback_plan` (bool), and the `trace_id`/`agent_run_id` correlation fields.
- `RunMetricsAccumulator.finalize()` gains a `self_check_passed: bool | None` parameter. The `agent_run_completed` event gains a `self_check_passed` field.
- `RunMetricsAccumulator.record_model_call()` is called once for the plan step and once for the synthesis step, so token and cost tracking covers both LLM calls.

### Confidence calculator
No changes. The existing deterministic `_compute_confidence` already matches the ticket rules and all existing tests depend on its current behavior.

### Fallback behavior
- Plan failure → canned plan string, `fallback_plan: true` in trace, agent continues.
- Synthesis failure → deterministic `_synthesize_answer`, `synthesis_fallback: true` in response telemetry.
- Self-check failure → answer is still returned, `self_check.passed = false` with reason; caller decides what to do.

## Testing Decisions

**What makes a good test here:** test the behavior visible from the constructor and `answer()` return value. Do not assert on internal function calls. Mock the two LLM adapter calls via injected fakes that return deterministic strings.

**Flows to test:**
- Happy path: plan adapter returns a thought, synthesis adapter returns a grounded answer → `self_check.passed = True`, `confidence` is deterministic, trace event contains `plan` field.
- Groundedness failure: synthesis mock returns an answer containing `"currently gathering"` against seeded data → `self_check.passed = False`, answer is still returned.
- Plan adapter failure: plan mock raises → fallback plan string is used, agent still answers.
- Synthesis adapter failure: synthesis mock raises → deterministic fallback answer is used, `synthesis_fallback: true` in telemetry.
- Coordinator kwarg: constructing `FanGatheringAgent(coordinator=None)` and `FanGatheringAgent(coordinator=mock_coordinator)` do not raise; `mock_coordinator.delegate` is never called.
- `agent_run_completed` event: `self_check_passed` field is present and matches response.
- `agent_reasoning_step` trace event: emitted with correct `plan` and `tools_used` fields.
- All existing tests continue to pass without modification (mocks return strings compatible with existing answer-content assertions).

**Prior art:** existing `test_fan_gathering_agent.py` uses `_PartiallyDegradedMCP` and `_PartiallyFailingMCP` pattern — follow the same injectable-factory pattern for LLM adapters.

## Out of Scope

- Multi-step ReAct loops. There is exactly one plan → tool → answer cycle per request.
- LLM-based tool selection. The three tools are always called.
- Concrete `AgentCoordinator` implementation. That is Phase 04.
- Changes to the confidence calculator logic or label thresholds.
- LLM self-check enabled by default. It is opt-in and untested in the test suite.
- Any changes to the MCP tool implementations themselves.

## Further Notes

- The plan and synthesis LLM calls add latency. The plan call can be issued before tool dispatch (the tools are called after the plan string is received). The synthesis call is necessarily sequential after tool results are collected. Total added latency is approximately two Flash round-trips.
- Flash model is already wired through `ModelRouter` and `Settings.gemini_flash_model`. Both new adapters must use the same route — no new model config needed.
- The `GeminiFlashSynthesisAdapter` that already exists in `fan_gathering.py` should be refactored into the synthesis adapter role rather than duplicated.
- The self-check banned-phrase list should be a module-level constant so it can be extended without touching the function signature.
- Phase 04 dependency: the `AgentCoordinator` Protocol must be importable from `throughball_ai.orchestrator` by the time Phase 04 begins.
