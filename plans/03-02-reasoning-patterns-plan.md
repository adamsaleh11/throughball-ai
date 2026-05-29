# Plan: ReAct Reasoning Patterns for FanGatheringAgent

> Source PRD: plans/03-02-reasoning-patterns.md

## Architectural decisions

- **LLM boundary**: Flash only (`gemini-2.0-flash-001`), routed through existing `ModelRouter` — no new model config needed
- **Adapters**: Plan and synthesis steps are injected callables (Protocol-typed), defaulting to real Flash adapters in production; tests inject mocks returning deterministic strings
- **Tool dispatch**: Always 3 fixed tools in parallel — unchanged from current implementation
- **Confidence**: Deterministic `_compute_confidence` — no changes
- **Trace**: JSONL append via existing pattern; new `agent_reasoning_step` event type alongside existing `agent_run_completed`
- **Coordinator**: `AgentCoordinator` Protocol lives in `throughball_ai.orchestrator`, stored on agent but never called until Phase 04
- **Fallback chain**: Plan failure → canned plan string; Synthesis failure → deterministic `_synthesize_answer`; Self-check failure → answer still returned with `self_check.passed = false`

---

## Phase 1: Plan Step (Thought + Trace)

**User stories**: 1, 5, 6, 10, 12, 14

### What to build

Add a plan adapter that calls Flash to generate a brief reasoning thought before tool dispatch. The thought is logged as an `agent_reasoning_step` trace event containing `plan`, `tools_used`, and `fallback_plan` fields alongside the existing correlation IDs. When the Flash call fails, a canned fallback plan string is used and `fallback_plan: true` is set in the trace. The three tool calls remain in parallel and are unaffected by the plan step.

### Acceptance criteria

- [ ] `FanGatheringAgent` accepts an optional `plan_adapter` constructor argument
- [ ] The plan step runs before tool dispatch on every `answer()` call
- [ ] A `agent_reasoning_step` trace event is emitted with `plan`, `tools_used`, `fallback_plan`, `trace_id`, and `agent_run_id` fields
- [ ] When `plan_adapter` raises, a canned plan string is used and `fallback_plan: true` in the trace event
- [ ] The three tool calls still run in parallel and are always called
- [ ] Mock `plan_adapter` injected in tests — no live Flash calls

---

## Phase 2: LLM Synthesis

**User stories**: 1, 6, 10, 15

### What to build

Replace the deterministic `_synthesize_answer` as the primary answer path with a synthesis adapter that calls Flash with the reasoning thought + tool observations. The deterministic synthesizer remains as a fallback. Both the plan LLM call and the synthesis LLM call are tracked through `RunMetricsAccumulator.record_model_call()` so token counts and cost estimates cover the full ReAct cycle.

### Acceptance criteria

- [ ] `FanGatheringAgent` accepts an optional `synthesis_adapter` constructor argument
- [ ] The synthesis adapter is called with `thought`, `tool_results`, `confidence`, and `max_chars`
- [ ] When `synthesis_adapter` raises, `_synthesize_answer` is used and `synthesis_fallback: true` appears in response telemetry
- [ ] `record_model_call` is invoked for both the plan step and the synthesis step
- [ ] `agent_run_completed` event includes token and cost fields reflecting both LLM calls
- [ ] Mock `synthesis_adapter` injected in tests — returns strings compatible with existing answer-content assertions
- [ ] All existing `test_fan_gathering_agent.py` tests continue to pass

---

## Phase 3: Groundedness Self-Check

**User stories**: 3, 4, 7, 11

### What to build

Add a pure deterministic `_groundedness_check` function that inspects the synthesized answer for banned freshness phrases (`"currently"`, `"right now"`, `"live"`, `"confirmed gathering"`, `"are there now"`) when any tool result has `source_type` in `{"seeded", "cached"}`. The result (`{"passed": bool, "reason": str}`) is attached to the agent response as `self_check` and to the `agent_run_completed` event as `self_check_passed`. An opt-in `llm_self_check` constructor flag (default `False`) is wired but never exercised in the test suite.

### Acceptance criteria

- [ ] `_groundedness_check` is a pure function — no LLM call, no I/O
- [ ] Banned phrases against seeded/cached sources produce `passed: false` with a non-empty `reason`
- [ ] Grounded answers against seeded/cached sources produce `passed: true`
- [ ] Agent response includes `self_check: {"passed": bool, "reason": str}`
- [ ] `agent_run_completed` event includes `self_check_passed` field
- [ ] `llm_self_check=False` (default) never triggers an LLM call
- [ ] Banned phrase list is a module-level constant

---

## Phase 4: AgentCoordinator Protocol Stub

**User stories**: 8, 9

### What to build

Define an `AgentCoordinator` Protocol in `throughball_ai.orchestrator` with a single async `delegate(agent_name: str, request: dict) -> dict` method. `FanGatheringAgent` gains an optional `coordinator: AgentCoordinator | None = None` constructor argument that is stored but never called. No concrete implementation is provided — that is Phase 04's responsibility.

### Acceptance criteria

- [ ] `AgentCoordinator` is importable from `throughball_ai.orchestrator`
- [ ] `AgentCoordinator` defines `async def delegate(self, agent_name: str, request: dict) -> dict`
- [ ] `FanGatheringAgent(coordinator=None)` constructs without error
- [ ] `FanGatheringAgent(coordinator=mock_coordinator)` constructs without error and `mock_coordinator.delegate` is never called during `answer()`
- [ ] No new model calls, trace events, or runtime cost is introduced by this phase
