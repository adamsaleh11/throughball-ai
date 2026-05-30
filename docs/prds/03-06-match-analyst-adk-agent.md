# PRD 03-06 — Match Analyst ADK Agent

> Ticket: `tickets/phase-03/03-06-match-analyst-adk-agent.md` (Doc 2 ticket 09-03)
> Agent: `match_analyst` (`MatchAnalystADKAgent`)
> Phase: 03 — Google ADK agents
> Status: Ready for planning

## Problem Statement

Throughball fans watching a World Cup match want to understand *what is happening
tactically and why*, not just the scoreline. Today the companion app has agents for
fan gathering (03-04) and city concierge (03-05), but nothing that explains the match
itself: momentum shifts, tactical context, how the current state compares to a team's
history, and what it implies for the rest of the game.

A naive "ask an LLM about the match" approach fails the project on two fronts:

1. **Trust.** Fans cannot tell which statements are grounded match facts (score, minute,
   goal events) versus the model's tactical opinion. Ungrounded, confident-sounding
   analysis is worse than no analysis.
2. **Cost.** This is a side project with a hard cost ceiling. An analyst agent that
   debates with itself, loops on retrieval, or escalates to expensive models would make
   the running cost unpredictable.

We need an agent that gives evidence-backed match analysis, visibly separates fact from
inference, reports its own confidence, and runs on a tight, predictable cost budget.

## Solution

Add a `MatchAnalystADKAgent` built on Google ADK (`LlmAgent`) that answers match-analysis
questions using three seeded tools — `get_match_state`, `get_team_profile`, and
`search_documents` — under a ReAct tool-use loop owned by the model.

From the user's perspective the agent:

- Explains the current match state (score, clock, momentum) with concrete evidence and
  citations to the data/documents it used.
- Clearly separates **facts** (values that came from a tool) from **inferences** (tactical
  or momentum reasoning the model derived from those facts).
- Reports a **confidence** level with a short rationale, and degrades gracefully (flagging
  the answer) when grounding is missing rather than bluffing.
- Runs on **Gemini Flash only**, with a bounded tool/token budget so each request has a
  small, predictable cost. Every response carries real `cost_per_request` and
  `tokens_per_second` metrics.

The agent reuses the proven structure of the Fan Gathering agent (callback-based budget
enforcement, telemetry hooks, deterministic post-processing) and routes its metrics through
the existing `build_llm_metrics` helper so cost/throughput numbers are computed from real
token usage rather than placeholders.

## User Stories

1. As a fan, I want the agent to explain the current match state in plain language, so that
   I understand what is happening beyond the scoreline.
2. As a fan, I want each factual statement (score, minute, who scored) tied to the match
   data it came from, so that I can trust it.
3. As a fan, I want tactical and momentum statements clearly labeled as inference, so that I
   don't mistake an opinion for a fact.
4. As a fan, I want historical/contextual comparisons (e.g. how a team typically plays) to
   cite the team profile or a retrieved document, so that the comparison is grounded.
5. As a fan, I want a confidence indicator with a one-line reason, so that I know how much to
   rely on the analysis.
6. As a skeptical fan, I want the agent to say when it lacks enough grounded data rather than
   guess, so that I'm not misled.
7. As a fan asking a simple "what's the score and momentum" question, I want a fast cheap
   answer that only reads match state, so that trivial questions don't cost extra.
8. As a fan asking a team- or history-heavy question, I want the agent to pull team profile
   and documents as needed, so that the answer is well-supported.
9. As an operator, I want every request capped at 4 tool calls, so that runaway tool usage
   can't happen.
10. As an operator, I want retrieval capped at 5 chunks and duplicate retrieval calls
    suppressed, so that retrieval cost and latency stay bounded.
11. As an operator, I want the agent to never use a Pro model, so that cost stays minimal
    and predictable for a side project.
12. As an operator, I want each response to include `cost_per_request` and
    `tokens_per_second` computed from real token usage, so that I can monitor spend and
    throughput.
13. As an operator, I want a structured trace (agent/model/tool spans) emitted per run via
    the existing telemetry hooks, so that the analyst is observable like the other agents.
14. As a developer, I want the agent to degrade (not crash) when a tool errors or returns no
    data, so that a single bad tool result doesn't fail the request.
15. As a developer, I want the response shape documented in a contract, so that downstream
    callers can integrate against a stable schema.
16. As a fan, I want the answer length bounded, so that the response stays readable on
    mobile.

## Implementation Decisions

### Modules

- **`MatchAnalystADKAgent`** (new) — the deep module. Public interface is a single
  `answer(...)` coroutine returning a structured dict. Internally it owns: MCP tool
  wrappers, ADK `LlmAgent` construction, budget/telemetry callbacks, answer extraction, the
  deterministic self-check, fact/inference parsing, citation assembly, confidence
  computation, and metrics. Built structurally from `FanGatheringADKAgent`.
- **Settings** (modified) — no new model fields. The agent uses the existing
  `gemini_flash_model`, `max_output_tokens`, `default_temperature`, and
  `max_agent_iterations`. **No `gemini_pro_model` and no `allow_pro_model`/`ALLOW_PRO_MODEL`
  are added** — Pro is intentionally absent from the entire surface.
- **Reused as-is**: `AdkCallbackHooks` (telemetry spans), `build_llm_metrics` (real
  cost/throughput from usage), `estimate_model_cost` (Flash pricing), `new_id` (trace IDs),
  `build_mcp_server` (tool dispatch).

### Model routing

- **Gemini Flash only** (`settings.gemini_flash_model`, currently `gemini-2.0-flash-001`).
- No Pro model, no escalation flag, no model-routing branch anywhere. `answer()` has **no**
  `escalate` parameter.

### Tools and the ReAct loop

The model owns dispatch via ADK ReAct. Three FunctionTool wrappers:

- `get_match_state(match_id, include_timeline=True)` — `include_timeline=True` by default
  because the timeline is the primary momentum evidence.
- `get_team_profile(team_id, include_evidence=True)` — team context, supporter notes, and
  `evidence_ids` used for citations.
- `search_documents(query, top_k=5)` — historical/tactical document grounding.

All wrappers call with `allow_external=False` (seeded data only) and use the same
try/except → degraded-result pattern as Fan Gathering.

**Tool usage policy:** the system instruction directs the model to *always* call
`get_match_state`, and to call `get_team_profile` / `search_documents` **only when** the
query needs team context or historical/document grounding. Tools are not force-called every
turn, so simple "score + momentum" questions cost a single tool call.

### Cost rules (enforced in Python, not by trusting the prompt)

- **Max 4 tool calls** — counter in ADK session state via `before_tool_callback`; the 5th
  call is refused with an error result.
- **Max 5 retrieved chunks** — `search_documents` is always called with `top_k=5` and the
  wrapper hard-truncates results to 5.
- **No retrieval loops** — the `search_documents` wrapper dedupes: a repeat call with an
  already-seen query returns the cached first result (and still counts against the 4-call
  budget).
- **No multi-agent debate** — a single `LlmAgent`, no sub-agents.
- **Bounded output** — agent-level `GenerateContentConfig(max_output_tokens=384)` (lower
  than the global default to cap the most expensive token class). `RunConfig(max_llm_calls=
  settings.max_agent_iterations)`.
- **Answer truncation** — `max_answer_chars=1200` as a separate readability guard.

### Self-check for unsupported claims

Deterministic, no extra LLM call, no re-prompt loop:

1. The system instruction asks the model to mark facts vs inferences and emit `[N]` citation
   markers tied to retrieved evidence.
2. A Python groundedness check verifies that (a) every `[N]` marker resolves to a real
   retrieved chunk or `evidence_id`, and (b) claims about score/minute/momentum are backed
   by a `get_match_state` result. On failure the response is flagged `degraded=True` with a
   reason; the agent does **not** re-query or loop.

### Facts vs inference separation

The response carries two distinct lists: `facts[]` (each `{claim, source}`, backed by a tool
value) and `inferences[]` (each `{claim, basis}`, tactical/momentum reasoning derived from
facts). The answer text uses explicit "Fact:" / "Inferred:" markers so the separation is
visible and machine-checkable by the self-check.

### Citations

Citations come only from real tool output — no fabricated `source_N` entries:

- `search_documents` chunks → `[N]` markers mapped to the chunk's real `source_path`/title.
- `get_team_profile.data.evidence_ids` → citable evidence references.
- `get_match_state` is attributed as a data source ("per cached match state") rather than a
  `[N]` document citation.

### Confidence

Response includes a `confidence` label (`high` / `medium` / `low`) plus a
`confidence_details` object (contributors + downgrade_reasons), mirroring Fan Gathering's
shape. Rules:

- `high` only if match state is present AND at least one supporting document/evidence is
  present AND no tool degraded.
- `low` if match state is missing/degraded or there is zero grounding.
- otherwise `medium`.
- Seeded data caps confidence at `medium` for live-momentum claims (the data is cached, not
  truly live).

### Response schema (`answer()` return dict)

`answer`, `facts`, `inferences`, `confidence`, `confidence_details`, `citations`,
`grounded`, `degraded`, `degraded_reason`, `self_check`, `tool_sources`, `model_name`,
`metrics` (containing real `cost_per_request`, `tokens_per_second`, `tool_call_count`,
`total_latency_ms`, `prompt_tokens`, `completion_tokens`).

### Method signature

`answer(*, query, session_id, match_id, home_team_id=None, away_team_id=None,
max_answer_chars=1200)`. Because `get_match_state` returns both `home_team_id` and
`away_team_id`, team-profile lookups can be driven from match-state output when the caller
omits the team IDs.

## Testing Decisions

Mirror `tests/test_fan_gathering_adk_agent.py`: inject a stub `BaseLlm` and a stub
`mcp_factory` so no live model or DB is needed. Test external behavior and the response
contract, not internals. Coverage to call out explicitly:

1. Facts and inferences are returned as separate populated lists for a normal query.
2. Citations map to real retrieved chunks / `evidence_ids` (no fabricated sources).
3. The self-check flags an unsupported claim and sets `degraded=True` with a reason.
4. The tool-call budget is capped at 4 (5th call refused).
5. Retrieved chunks are capped at 5 even if the tool returns more.
6. A repeated `search_documents` query is deduped (no second underlying call).
7. The agent always uses the Flash model (only one model path exists).
8. `metrics` contains real `cost_per_request` and `tokens_per_second` derived from stubbed
   token usage (non-placeholder).
9. A tool error degrades gracefully rather than raising.
10. Confidence downgrades to `medium`/`low` per the rules (seeded-data cap; missing grounding).

## Out of Scope

- Any Pro model, model routing, or escalation logic.
- Real-time / live match data — all tools return seeded/cached data.
- Multi-agent debate, self-consistency, or retrieval-refinement loops.
- New MCP tools — `get_match_state`, `get_team_profile`, `search_documents` already exist.
- Wiring the agent into an HTTP/API surface or UI — this PRD covers the agent module and its
  contract only.
- Changes to the cost/pricing tables (Flash pricing already present in `costs.py`).

## Further Notes

- **Deliverables:** this PRD, a matching plan (`plans/03-06-match-analyst-adk-agent.md`),
  and a response contract (`docs/contracts/match-analyst-agent.md`) after implementation —
  consistent with the 03-04 / 03-05 cadence.
- **Assumption:** `search_documents` chunk results expose a stable per-chunk identifier
  (e.g. `source_path`/title) to map `[N]` markers; confirm the exact field names from the
  tool output schema during planning.
- **Cost posture:** Flash-only + `max_output_tokens=384` + single-tool common case are the
  primary cost levers; revisit only if analysis quality is visibly starved.
- **Open question:** whether `query` is required or can default to a generic "analyze this
  match" prompt when only `match_id` is supplied (lean: default it, like the prior agents).
