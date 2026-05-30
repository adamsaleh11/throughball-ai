# Match Analyst Agent — Response Contract

> Agent: `match_analyst` (`MatchAnalystADKAgent`)
> Module: `src/throughball_ai/agents/match_analyst_adk.py`
> Introduced: 03-06 (Doc 2 ticket 09-03)

This contract documents the shape of the dict returned by
`MatchAnalystADKAgent.answer()`.

The agent is **Flash-only by design** — there is no Pro model, no `ALLOW_PRO_MODEL`
flag, and no model-routing/escalation path anywhere in the module. This keeps
per-request cost small and predictable.

---

## Method signature

```python
await agent.answer(
    query: str | None = None,      # natural-language question; defaults to a generic analysis prompt
    session_id: str = "",          # caller session id, used for telemetry correlation
    match_id: str,                 # required (keyword-only)
    home_team_id: str | None = None,
    away_team_id: str | None = None,
    max_answer_chars: int = 1200,
) -> dict
```

`get_match_state` returns both `home_team_id` and `away_team_id`, so team-profile
lookups can be driven from match-state output when the caller omits the team IDs.

---

## Tools and cost rules

The LLM owns tool dispatch (ReAct). Three tools are available:

- `get_match_state(match_id, include_timeline=True)` — always called first.
- `get_team_profile(team_id, include_evidence=True)` — only when team context is needed.
- `search_documents(query, top_k=5)` — only when document grounding is needed.

Enforced in Python (not by trusting the prompt):

- **Max 4 tool calls** per run (`before_tool_callback` counter in session state).
- **Max 5 retrieved chunks** (`top_k=5` and hard truncation of `chunks`/`results`).
- **No retrieval loops** — a repeated `search_documents` query is served from cache and
  does not issue a second underlying call.
- **No multi-agent debate** — a single `LlmAgent`.
- **Bounded output** — `max_output_tokens=384`; answer truncated to `max_answer_chars`.

---

## Response shape

```json
{
  "answer": "Fact: The home team leads 2-1 at minute 67. Inferred: The home team has momentum after the recent goal. Historical context: this team protects 2-1 leads well [1].",
  "facts": [
    {"claim": "The home team leads 2-1 at minute 67.", "source": "get_match_state"},
    {"claim": "The home team scored at minute 64.", "source": "get_match_state"}
  ],
  "inferences": [
    {"claim": "The home team has momentum after the recent goal.", "basis": "Derived from grounded match facts."}
  ],
  "confidence": "medium",
  "confidence_details": {
    "label": "medium",
    "contributors": ["Match state is available.", "Supporting documents/evidence are cited."],
    "downgrade_reasons": ["Momentum claims rest on seeded (cached) match data, not live."]
  },
  "citations": [
    {"id": 1, "source_path": "knowledge/home_team_history.md", "title": "Home Team History"},
    {"id": null, "source_path": "doc_123", "title": "Team profile evidence"}
  ],
  "grounded": true,
  "degraded": false,
  "degraded_reason": null,
  "self_check": {"passed": true, "reason": "All citations resolve and match claims are grounded."},
  "tool_sources": [
    {"tool": "get_match_state", "source_type": "seeded", "degraded": false, "external_api_called": false},
    {"tool": "search_documents", "source_type": "internal", "degraded": false, "external_api_called": false}
  ],
  "model_name": "gemini-2.0-flash-001",
  "metrics": {
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200,
    "tokens_per_second": 53.33,
    "latency_ms": 1500,
    "estimated_cost": 0.000033,
    "cost_per_request": 0.000033,
    "model_name": "gemini-2.0-flash-001",
    "tool_call_count": 2,
    "retry_count": 0,
    "degraded": false,
    "total_latency_ms": 1500,
    "tool_latencies": {"get_match_state": 3, "search_documents": 5}
  }
}
```

---

## Field reference

| Field | Type | Notes |
|---|---|---|
| `answer` | `str` | Model text, truncated to `max_answer_chars`. Uses `Fact:` / `Inferred:` markers and `[N]` citation markers. |
| `facts` | `list[{claim, source}]` | Grounded statements. `source` is the tool that backs the claim. |
| `inferences` | `list[{claim, basis}]` | Tactical/momentum interpretation derived from facts — never presented as fact. |
| `confidence` | `"high" \| "medium" \| "low"` | See rules below. |
| `confidence_details` | `{label, contributors[], downgrade_reasons[]}` | Rationale for the label. |
| `citations` | `list[{id, source_path, title}]` | Numbered (`id`) citations map to real `search_documents` results; team-profile `evidence_ids` appear with `id: null`. No fabricated sources. |
| `grounded` | `bool` | True when citations exist or match state was retrieved. |
| `degraded` | `bool` | True when the self-check fails or any tool degraded. |
| `degraded_reason` | `str \| null` | Populated when `degraded` is true. |
| `self_check` | `{passed, reason}` | Deterministic groundedness check; never re-prompts or loops. |
| `tool_sources` | `list[{tool, source_type, degraded, external_api_called}]` | One entry per tool that ran. |
| `model_name` | `str` | Always a Flash model. |
| `metrics` | `object` | Real `cost_per_request` and `tokens_per_second` derived from `usage_metadata` via `build_llm_metrics`. |

---

## Confidence rules

- `high` — match state present **and** supporting documents/evidence cited **and** no tool degraded.
- `low` — match state missing/degraded, or any tool degraded.
- `medium` — otherwise.
- **Seeded cap:** when the answer makes a live-momentum claim and match data is seeded
  (cached, not live), confidence is capped at `medium` with a downgrade reason.

## Self-check rules (deterministic, no loop)

1. Every `[N]` citation marker must resolve to a retrieved document chunk; an unresolved
   marker fails the check.
2. Any score/minute/momentum claim must be backed by a `get_match_state` result.

On failure, the response is flagged `degraded=True` with a reason; the agent does **not**
re-query or re-prompt.
