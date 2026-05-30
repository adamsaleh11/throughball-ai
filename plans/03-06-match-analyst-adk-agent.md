# Plan: Match Analyst ADK Agent

> Source PRD: docs/prds/03-06-match-analyst-adk-agent.md (ticket 03-06 / Doc 2 09-03)

## Architectural decisions

Durable decisions that apply across all phases:

- **Agent**: `MatchAnalystADKAgent` in `src/throughball_ai/agents/match_analyst_adk.py`, public coroutine `answer(*, query, session_id, match_id, home_team_id=None, away_team_id=None, max_answer_chars=1200)`. Built structurally from `FanGatheringADKAgent`.
- **Model**: Gemini Flash only (`settings.gemini_flash_model`). No Pro model, no `gemini_pro_model`, no `allow_pro_model`/`ALLOW_PRO_MODEL`, no escalation logic anywhere. No settings changes required.
- **Tools**: `get_match_state(match_id, include_timeline=True)`, `get_team_profile(team_id, include_evidence=True)`, `search_documents(query, top_k=5)`. All called with `allow_external=False`. Dispatched via `build_mcp_server`.
- **Tool policy**: always call `get_match_state`; call `get_team_profile`/`search_documents` only when the query needs team or document grounding. Model owns dispatch (ReAct).
- **Cost rules**: max 4 tool calls (`before_tool_callback` counter in session state); max 5 chunks (`top_k=5` + truncate); dedupe repeated `search_documents` queries; single `LlmAgent` (no sub-agents); `GenerateContentConfig(max_output_tokens=384)`; `RunConfig(max_llm_calls=settings.max_agent_iterations)`; answer truncated to 1200 chars.
- **Metrics**: routed through `build_llm_metrics` (real `cost_per_request`, `tokens_per_second` from `usage_metadata`). Telemetry spans via `AdkCallbackHooks`.
- **Response shape**: `answer, facts, inferences, confidence, confidence_details, citations, grounded, degraded, degraded_reason, self_check, tool_sources, model_name, metrics`.
- **Citations**: only from real tool output — `search_documents` chunk `source_path`/title and `get_team_profile.evidence_ids`. No fabricated `source_N`. `get_match_state` attributed as a data source, not a `[N]` doc citation.
- **Tests**: mirror `tests/test_fan_gathering_adk_agent.py` — stub `BaseLlm` + stub `mcp_factory`, no live model/DB.

---

## Phase 1: Tracer bullet — Flash-only analyst skeleton

**User stories**: 1, 7, 11, 12, 13, 16

### What to build

A minimal working `MatchAnalystADKAgent.answer()` that constructs the ADK `LlmAgent` on Flash only, wraps `get_match_state`, enforces the 4-call budget via `before_tool_callback`, wires `AdkCallbackHooks` plus before/after model and tool callbacks (capturing `usage_metadata`), and returns a response with `answer`, `model_name`, `tool_sources`, and a `metrics` block whose `cost_per_request` and `tokens_per_second` come from `build_llm_metrics`. Output bounded to 384 tokens / 1200 chars.

### Acceptance criteria

- [ ] `answer()` runs end-to-end with a stubbed model and returns answer text from `get_match_state`.
- [ ] Only the Flash model is ever used; no Pro/escalation code path exists.
- [ ] `metrics.cost_per_request` and `metrics.tokens_per_second` are computed from real (stubbed) token usage — not placeholder constants.
- [ ] Tool-call budget caps at 4 (5th call refused).
- [ ] `max_output_tokens=384` is applied on the agent's generate config; answer truncated to 1200 chars.

---

## Phase 2: Full toolset + cost rules

**User stories**: 8, 9, 10, 14

### What to build

Add `get_team_profile` and `search_documents` tool wrappers with the on-demand usage policy in the system instruction. Enforce the retrieval cost rules: `search_documents` always called with `top_k=5` and truncated to 5 chunks; repeated calls with an already-seen query return the cached first result (still counted against the budget). Tool errors produce a degraded result instead of raising.

### Acceptance criteria

- [ ] A team/history question causes `get_team_profile` and/or `search_documents` to be called; a score-only question calls just `get_match_state`.
- [ ] Retrieved chunks are capped at 5 even when the tool returns more.
- [ ] A repeated `search_documents` query is deduped (no second underlying tool call) and still counts toward the 4-call budget.
- [ ] A raised tool exception yields a degraded tool result and the run completes.

---

## Phase 3: Facts vs inference + citations

**User stories**: 2, 3, 4

### What to build

Parse the model output into `facts[]` (`{claim, source}`) and `inferences[]` (`{claim, basis}`), with explicit "Fact:"/"Inferred:" markers in the instruction. Assemble `citations` from real tool output only: `search_documents` chunk identifiers and `get_team_profile.evidence_ids`; attribute `get_match_state` as a data source.

### Acceptance criteria

- [ ] Response returns separate, populated `facts` and `inferences` lists for a normal query.
- [ ] Citations map to real retrieved chunks / `evidence_ids`; no fabricated `source_N` entries appear.
- [ ] Match-state values are attributed as a data source rather than a `[N]` document citation.

---

## Phase 4: Self-check, confidence & degradation

**User stories**: 5, 6

### What to build

A deterministic Python groundedness self-check: every `[N]` marker must resolve to a retrieved chunk/evidence_id, and score/minute/momentum claims must be backed by `get_match_state`. On failure set `degraded=True` with a reason and populate `self_check` — no re-query or loop. Compute `confidence` (`high`/`medium`/`low`) plus `confidence_details` (contributors + downgrade_reasons), with seeded data capping live-momentum confidence at `medium`.

### Acceptance criteria

- [ ] An unsupported claim (unresolved `[N]` or momentum claim with no match_state) sets `degraded=True` with a reason and a failed `self_check`.
- [ ] No re-prompt/retrieval loop occurs on self-check failure.
- [ ] Confidence is `high` only with match_state + supporting doc/evidence + no degraded tools; `low` when match_state missing/degraded or no grounding; seeded data caps at `medium`.

---

## Phase 5: Response contract doc

**User stories**: 15

### What to build

Write `docs/contracts/match-analyst-agent.md` documenting the final `answer()` signature and complete response shape with an example, matching the format of `docs/contracts/fan-gathering-agent.md`.

### Acceptance criteria

- [ ] Contract documents the method signature and every response key with types.
- [ ] Includes a representative example response.
- [ ] Format is consistent with the existing fan-gathering contract.
