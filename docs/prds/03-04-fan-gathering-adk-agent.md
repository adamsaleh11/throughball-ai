# PRD: Rebuild Fan Gathering Agent as ADK Agent (03-04)

## Problem Statement

The Fan Gathering Agent built in Phase 05 (`05-03`) is a hand-rolled orchestration class: it calls tools in parallel unconditionally in Python, synthesizes answers with a bespoke template, and manages iterations, session tracking, and callbacks with custom infrastructure. It calls Gemini Flash only as an optional synthesis adapter, not as the reasoning core.

This creates two problems. First, it is architecturally inconsistent: the rest of the throughball-ai runtime is converging on `google.adk` as the agent execution layer, and a standalone Python class cannot benefit from ADK's callback lifecycle, session state management, model configuration, or runner infrastructure. Second, the existing agent bypasses the ADK execution model entirely for tool dispatch and synthesis — ADK is treated as a thin wrapper around a raw `genai` call rather than an agentic loop owner.

The immediate trigger is Phase 03's mandate to establish ADK as the standard agent contract across all agents. The Fan Gathering Agent is the first to be migrated and will serve as the reference implementation for subsequent agents (city concierge, itinerary).

## Solution

Replace the existing `FanGatheringAgent` class with a proper `LlmAgent`-backed agent using `google.adk`. The new agent will:

- Be constructed as a `google.adk.agents.LlmAgent` with Gemini Flash as its default model
- Delegate tool dispatch to ADK — the LLM decides when to call tools based on a system instruction that mandates calling all three required tools
- Wrap the three MCP tools (`get_fan_hotspots`, `get_city_events`, `get_venues`) as ADK-compatible `FunctionTool` callables that route through the existing MCP middleware boundary
- Enforce a hard cap of 3 tool calls per run using `before_tool_callback`, with the counter bound to ADK session state (not a Python closure)
- Enforce iteration limits via `RunConfig(max_llm_calls=...)` derived from settings
- Wire `AdkCallbackHooks` to ADK's native callback slots for tracing and metrics
- Apply a Python post-processor to the LLM-generated answer that (a) enforces the "Cached matchday data suggests…" prefix for seeded data and (b) sweeps for banned freshness phrases, setting `degraded: true` with a reason if any are found
- Return a structured response matching the updated contract, which adds `model_name` and `metrics` and retires the old `telemetry` top-level key

After the new agent passes its full test suite and one manual smoke test against real Gemini Flash, the old agent file and its tests are deleted.

## User Stories

1. As a fan, I want to ask where Argentina fans are gathering, so that the ADK agent retrieves hotspot, event, and venue data and returns a grounded short answer.
2. As a fan, I want the answer to begin with "Cached matchday data suggests…" when the underlying data is seeded or cached, so that I am never misled into thinking the system is tracking live crowds.
3. As a fan, I want answers to distinguish verified signals from inferred signals, so that I can judge how strong the recommendation is.
4. As a fan, I want confidence included in the response, so that I know whether to rely on the answer or treat it as a low-confidence lead.
5. As a fan, I want answers capped at 480 characters (the mobile chat bubble limit without scroll), so that the response is readable without further truncation by a UI layer.
6. As a developer, I want the agent implemented as a `google.adk.agents.LlmAgent`, so that it participates in the ADK execution lifecycle (callbacks, session, runner).
7. As a developer, I want the agent to use Gemini Flash (gemini-2.5-flash) as its default model, so that inference cost stays low and the Pro model is structurally excluded.
8. As a developer, I want the LLM to own tool dispatch via system instruction, so that the agent is a genuine agentic loop rather than a Python-orchestrated stub with a generation call bolted on.
9. As a developer, I want MCP tools wrapped as ADK `FunctionTool` callables that call through `mcp.call_tool()`, so that the MCP middleware boundary (tracing, budget, cache, retry, timeout) is preserved.
10. As a developer, I want `search_documents` excluded from this agent's tool set, so that the agent stays within its bounded 3-tool contract.
11. As a developer, I want tool call count enforced to a maximum of 3 via `before_tool_callback`, so that no model iteration can exceed the budget.
12. As a developer, I want the tool call counter stored in ADK session state, not a Python closure, so that concurrent `run_async` calls do not contaminate each other's budget.
13. As a developer, I want iteration count limited via `RunConfig(max_llm_calls=...)` drawn from `Settings.max_agent_iterations`, so that the limit is configurable without code changes.
14. As a developer, I want `AdkCallbackHooks.on_model_completed` wired to ADK's `after_model_callback`, so that model latency and token usage are emitted as structured events.
15. As a developer, I want `AdkCallbackHooks.on_tool_completed` wired to ADK's `after_tool_callback`, so that tool status, latency, and degraded state are emitted per call.
16. As a developer, I want `AdkCallbackHooks.on_agent_completed` called once after the runner loop ends, so that the full run summary event (confidence, total latency, tool latencies) is emitted.
17. As a developer, I want a Python post-processor to enforce the "Cached matchday data suggests…" prefix on answers backed by seeded or cached sources, so that the safety policy does not depend solely on the LLM honoring the system instruction.
18. As a developer, I want a Python post-processor to sweep the LLM answer for banned freshness phrases (`currently`, `right now`, `live`, `confirmed gathering`, `are there now`) and set `degraded: true` if any are found, so that safety violations are surfaced explicitly rather than silently returned.
19. As a developer, I want confidence and evidence assembly (`evidence_summary`, `verified_signals`, `inferred_signals`, `tool_sources`) computed deterministically in Python from tool results, so that safety-sensitive framing is not delegated to the LLM.
20. As a developer, I want the response to include `model_name` and `metrics`, so that the caller can inspect which model ran and aggregate cost and latency data.
21. As a developer, I want the `telemetry` top-level key replaced by `metrics` in the response shape, so that the contract is consistent with the ADK agent pattern going forward.
22. As a developer, I want a contract change note and an update to `docs/contracts/` in the same PR, so that consumers of the old shape (Phase 06 FastAPI runtime, Phase 06-03 UI) have an explicit migration signal.
23. As a developer, I want tests to use a `_StubLlm` subclassing `BaseLlm` with no live API calls, so that CI remains deterministic and credential-free.
24. As a developer, I want `_StubLlm` to be parameterized across four scenarios — (a) all 3 tools + final text (happy path), (b) only 2 tools emitted then stop (missing data handling), (c) 4 tool calls attempted (cap enforcement), (d) text-only with no tool calls (degraded path) — so that failure modes are covered by test, not discovered in production.
25. As a developer, I want MCP tool injection to remain mockable via an `mcp_factory` parameter on the agent wrapper, so that tests can substitute a fake MCP without touching the ADK layer.
26. As a developer, I want one clearly-marked manual smoke test (`@pytest.mark.smoke`) that runs the agent against real Gemini Flash, so that integration with the live model is verified before the old code is deleted.
27. As an operator, I want `model_name` in the response to be verifiable as containing `"flash"` and not containing `"pro"`, so that the Gemini Flash-only policy is testable in CI.
28. As an operator, I want `metrics` to include `tool_call_count`, `total_latency_ms`, and `tool_latencies` (a dict keyed by tool name), so that per-request cost and latency are observable without parsing log events.
29. As a developer, I want the old `FanGatheringAgent` class, its test file, and any import references to both deleted only after the new agent's tests pass and the smoke test completes, so that there is no window where neither agent works.

## Implementation Decisions

**Agent construction**
- The agent is a `google.adk.agents.LlmAgent` with `name="fan_gathering"`, `model="gemini-2.5-flash"` (read from `Settings.gemini_flash_model`), and tools wired from the MCP factory.
- The system instruction is embedded at construction time. It mandates calling all three tools, prohibits banned freshness phrases, requires the "Cached matchday data suggests…" prefix for seeded/cached data, distinguishes verified from inferred signals, and caps the answer at 480 characters.
- `generate_content_config` sets `max_output_tokens` and `temperature` from `Settings`.

**Tool wiring**
- Three thin async wrapper functions are created from the MCP server instance: one per tool (`get_fan_hotspots`, `get_city_events`, `get_venues`). Each wrapper calls `mcp.call_tool(name, args)` and returns the parsed result dict.
- Wrappers are registered with the `LlmAgent` as `FunctionTool` objects.
- The MCP server is built once per agent instance via an injected `mcp_factory` (defaulting to `build_mcp_server`). This keeps tests mockable.
- `search_documents` is not wired. No external API tools are wired.

**Execution model**
- A Python wrapper class (provisionally `FanGatheringADKAgent`) owns the runner lifecycle. It constructs the `LlmAgent`, creates an `InMemoryRunner` (using `google.adk.sessions.InMemorySessionService`), and exposes an `async def answer(request: FanGatheringRequest) -> dict` method.
- Per run: the wrapper creates a session, sets compact state (`city_id`, `match_id`, `team_id`, `tool_call_count: 0`) in session state, calls `runner.run_async(...)`, collects events, and runs post-processing.
- `RunConfig(max_llm_calls=settings.max_agent_iterations)` is passed to each `run_async` call.

**Tool call budget enforcement**
- `before_tool_callback` reads `state["tool_call_count"]` from the callback context. If it equals 3, the callback returns an error dict and does not allow the call. Otherwise it increments `state["tool_call_count"]` via `state_delta`.
- The counter is per-session and lives in ADK session state — not a closure.

**Callbacks**
- `AdkCallbackHooks` is instantiated once per agent instance.
- `after_model_callback` → calls `hooks.on_model_completed(...)` with model name, latency, and usage from the event.
- `after_tool_callback` → calls `hooks.on_tool_completed(...)` with tool name, status, and latency.
- `hooks.on_agent_completed(...)` is called once in the Python wrapper after the runner event loop finishes.
- The project's custom `AdkSession` / `InMemorySessionService` (from `throughball_ai.adk`) is used for the metrics accumulator — it is a separate telemetry concern from the ADK runner's session service.

**Python post-processing pipeline**
- After the runner loop, the Python wrapper extracts: (a) the final answer text from the last text-bearing event, (b) all tool result dicts from function-response events.
- Groundedness post-processor: if any source type in tool results is `"seeded"` or `"cached"` and the answer does not start with `"cached"` (case-insensitive), prepend `"Cached matchday data suggests "` and lowercase the first character of the original answer.
- Banned-phrase sweeper: if any banned freshness phrase is present in the answer, set `degraded: true` in the response and add a `degraded_reason` string naming the offending phrase.
- Confidence, `evidence_summary`, `verified_signals`, `inferred_signals`, and `tool_sources` are assembled in Python from tool result events using the existing deterministic logic (preserved from the old agent).

**Response contract change**
- New fields: `model_name` (string), `metrics` (dict with `tool_call_count`, `total_latency_ms`, `tool_latencies`).
- Removed field: `telemetry` (top-level). Its contents are folded into `metrics`.
- `confidence_details` is retained.
- `self_check` is retained for the groundedness check result.
- `docs/contracts/` is updated in the same PR to document the new shape.

**Migration sequencing**
1. New agent file written and tested (all unit tests pass, model mocked).
2. Manual smoke test run and noted as passed.
3. Old `fan_gathering.py` deleted.
4. Old `test_fan_gathering_agent.py` deleted.
5. `agents/__init__.py` updated.
6. Any imports across the codebase pointing to the old module updated.

## Testing Decisions

**What makes a good test here**
Tests must verify the agent's external contract and safety behavior, not its internal structure. Do not test that a specific callback method was called a specific number of times — test that the response contains `model_name`, that `degraded` is set when expected, and that banned phrases do not appear in answers.

**`_StubLlm` design**
- Subclasses `google.adk.models.BaseLlm`.
- Parameterized at construction: accepts a `scenario` enum with four values — `HAPPY`, `MISSING_TOOL`, `EXCEED_CAP`, `NO_TOOLS`.
- `HAPPY`: emits all 3 tool calls as a function-call event, then a seeded-prefixed answer as a text event.
- `MISSING_TOOL`: emits only 2 tool calls (`get_fan_hotspots`, `get_city_events`), then a text event. Verifies that the post-processor handles missing `get_venues` data without crashing.
- `EXCEED_CAP`: emits 4 tool calls. Verifies that `before_tool_callback` blocks the 4th and the run terminates gracefully.
- `NO_TOOLS`: emits only a text event with no tool calls. Verifies that the response is marked `degraded: true` and confidence is `"low"`.

**MCP mock**
- `mcp_factory` is injected as before: `mcp_factory=lambda: _MockMCP()`. The mock returns contract-shaped seeded responses per tool name.
- This is independent of the `_StubLlm` — tests compose both.

**Smoke test**
- Marked `@pytest.mark.smoke` and excluded from the default pytest run (`-m "not smoke"` in CI).
- Runs against real Gemini Flash with real MCP tool responses.
- Asserts `"flash"` in `response["model_name"]` and `"pro"` not in `response["model_name"]`.
- Does not assert a specific answer string — asserts structural validity and absence of banned phrases.

**Prior art for reference**
- `tests/test_fan_gathering_agent.py` — existing patterns for MCP mock injection, degraded assertions, tool source verification.
- `tests/test_adk_runtime.py` — existing patterns for callback hook assertions, session service usage, and LLM metrics checks.

**Coverage expected**
- Happy path: Argentina fans question → high/medium confidence, seeded prefix, 3 tool sources.
- Unknown team: low confidence, downgrade reason present.
- Fan zone question: answer contains "fan zone", seeded prefix.
- Degraded tool: one tool throws → `degraded: true`, remaining tools used for confidence.
- Budget cap: 4th tool call blocked by callback.
- No tools scenario: `degraded: true`, `confidence: "low"`.
- Post-processor: answer without seeded prefix is corrected; banned phrase triggers `degraded`.
- Model name: `"flash"` in `model_name`, `"pro"` not in `model_name`.
- Metrics shape: `tool_call_count`, `total_latency_ms`, `tool_latencies` all present.

## Out of Scope

- City concierge or itinerary agent migration — those are separate tickets.
- RAG / `search_documents` integration in this agent — explicitly excluded.
- External API calls — structurally blocked by `allow_external: false`.
- Persistent session storage — `InMemorySessionService` only.
- Multi-turn conversation — single-turn fan gathering questions only.
- Upgrading to Gemini 2.5 Pro or any reasoning model — structurally excluded.
- Adding new MCP tools beyond the three required.
- Phase 06 FastAPI endpoint wiring — the consumer updates for the contract change are out of scope for this ticket but flagged as a required follow-up.

## Further Notes

- **Contract breakage**: The `telemetry` → `metrics` rename is a breaking change for any consumer that inspects the agent response. Phase 06 FastAPI runtime and Phase 06-03 UI are the known downstream consumers. Both should be updated in a follow-up ticket or in the same PR if feasible. The `docs/contracts/` update must land in this PR.
- **480-character cap**: This is tied to the mobile chat bubble viewport — text beyond this requires scroll on the primary target device. It is a UX constraint, not an arbitrary number. It should be called out in a comment wherever the constant is defined.
- **gemini-2.5-flash availability**: At time of writing, `gemini-2.5-flash` is the intended model. If the model string is not yet available in the Vertex AI endpoint being used, fall back to `gemini-2.0-flash-001` via settings override. The Settings field `GEMINI_FLASH_MODEL` already handles this.
- **Smoke test credential requirement**: The manual smoke test requires `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and either Vertex AI credentials or a Gemini API key. Document this in the test file's docstring.
- **Dependency on Phase 02 tools**: `get_fan_hotspots`, `get_city_events`, and `get_venues` must all be registered and returning contract-shaped seeded data before this agent can be tested end-to-end. These are listed as "available after Phase 02" in the ticket and confirmed present in `mcp/tools/`.
- **ADK version**: The project is pinned to `google-adk>=0.1`; the installed version at time of writing is `2.1.0`. The `LlmAgent`, `FunctionTool`, `InMemoryRunner`, `BaseLlm`, and `RunConfig` interfaces used here are confirmed present in 2.1.0.
