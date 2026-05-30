# Fan Gathering Agent — Response Contract

> Agent: `fan_gathering` (`FanGatheringADKAgent`)
> Module: `src/throughball_ai/agents/fan_gathering_adk.py`
> Introduced: 03-04 (ADK rewrite)

This contract documents the shape of the dict returned by `FanGatheringADKAgent.answer()`.
The old `FanGatheringAgent` (03-02) returned a `telemetry` top-level key; **that key is
retired in this version**. Callers that read `response["telemetry"]` must migrate to
`response["metrics"]` and `response["tool_sources"]`.

---

## Method signature

```python
await agent.answer(
    city_id: str,
    match_id: str,
    team_id: str | None = None,
    question: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_answer_chars: int = 480,
) -> dict
```

---

## Response shape

```json
{
  "answer": "Cached matchday data suggests The Pub in Downtown is the best supporter gathering lead…",
  "confidence": "medium",
  "evidence_summary": [
    "get_fan_hotspots returned seeded data.",
    "get_city_events returned seeded data.",
    "get_venues returned seeded data."
  ],
  "verified_signals": ["Partner venue listing"],
  "inferred_signals": ["Near transit hub"],
  "degraded": false,
  "degraded_reason": null,
  "tool_sources": [
    {
      "tool": "get_fan_hotspots",
      "source_type": "seeded",
      "degraded": false,
      "external_api_called": false
    },
    {
      "tool": "get_city_events",
      "source_type": "seeded",
      "degraded": false,
      "external_api_called": false
    },
    {
      "tool": "get_venues",
      "source_type": "seeded",
      "degraded": false,
      "external_api_called": false
    }
  ],
  "model_name": "gemini-2.0-flash-001",
  "metrics": {
    "tool_call_count": 3,
    "total_latency_ms": 412,
    "tool_latencies": {
      "get_fan_hotspots": 38,
      "get_city_events": 29,
      "get_venues": 22
    }
  },
  "confidence_details": {
    "label": "medium",
    "contributors": [
      "Verified hotspot signals are present.",
      "Matchday event data supports the recommendation."
    ],
    "downgrade_reasons": [
      "Seeded data is not live crowd confirmation."
    ]
  },
  "self_check": {
    "passed": true,
    "reason": "Answer is grounded — no banned freshness phrases detected."
  }
}
```

---

## Field reference

| Field | Type | Always present | Description |
|---|---|---|---|
| `answer` | string | yes | Final answer text, ≤ `max_answer_chars` characters (default 480). |
| `confidence` | `"low"` \| `"medium"` \| `"high"` | yes | Deterministic confidence label derived from tool results. |
| `evidence_summary` | string[] | yes | One sentence per tool result, naming the tool and source type. |
| `verified_signals` | string[] | yes | Verified hotspot signals extracted from `get_fan_hotspots` results. May be empty. |
| `inferred_signals` | string[] | yes | Inferred hotspot signals extracted from `get_fan_hotspots` results. May be empty. |
| `degraded` | boolean | yes | `true` when any tool result was degraded, any tool timed out, or any banned phrase was found in the answer. |
| `degraded_reason` | string \| null | yes | Human-readable reason when `degraded` is `true`; `null` otherwise. |
| `tool_sources` | object[] | yes | One entry per tool that was called. See **Tool source shape** below. |
| `model_name` | string | yes | Model identifier confirmed from ADK response. Contains `"flash"`. Never contains `"pro"`. |
| `metrics` | object | yes | Run-level performance counters. See **Metrics shape** below. |
| `confidence_details` | object | yes | Structured explanation of the confidence label. |
| `self_check` | object | yes | Groundedness check result. `passed: false` when the answer contains a banned freshness phrase against seeded/cached data. |

### Tool source shape

| Field | Type | Description |
|---|---|---|
| `tool` | string | MCP tool name: `"get_fan_hotspots"`, `"get_city_events"`, or `"get_venues"`. |
| `source_type` | `"seeded"` \| `"cached"` \| `"external"` \| null | Source type from the tool response. `null` when the tool returned an error or degraded. |
| `degraded` | boolean | `true` when the tool timed out, returned `ok: false`, or the MCP middleware raised. |
| `external_api_called` | boolean | `true` when the tool made a live external API request. |

### Metrics shape

| Field | Type | Description |
|---|---|---|
| `tool_call_count` | integer | Number of MCP tool calls that completed (successful or degraded). Budget maximum is 3. |
| `total_latency_ms` | integer | Wall-clock latency of the entire `answer()` call in milliseconds. |
| `tool_latencies` | object | Map of tool name → latency in milliseconds for each tool that was called. |

---

## Safety invariants

These are enforced by Python post-processing after the ADK runner completes, not by the LLM.

1. **Prefix enforcer** — if any `tool_source.source_type` is `"seeded"` or `"cached"` and the answer does not begin with `"cached"` (case-insensitive), the prefix `"Cached matchday data suggests "` is prepended.

2. **Banned-phrase sweeper** — if any of the following phrases appear in the answer, `degraded` is set to `true` and `degraded_reason` names the offending phrase:
   - `"currently"`
   - `"right now"`
   - `" live "`
   - `"confirmed gathering"`
   - `"are there now"`

3. **Length cap** — the answer is truncated to `max_answer_chars` characters (default 480) after post-processing.

---

## Retired fields

| Field | Status | Migration |
|---|---|---|
| `response["telemetry"]` | **Removed** in 03-04 | Use `response["metrics"]` for counters/latencies and `response["tool_sources"]` for per-tool degradation state. |
| `response["telemetry"]["trace_id"]` | **Removed** in 03-04 | The `agent_run_completed` event emitted via `AdkCallbackHooks` carries `trace_id` for end-to-end tracing. |
| `response["telemetry"]["synthesis_fallback"]` | **Removed** in 03-04 | The LLM always synthesizes; no Python fallback path exists in the ADK agent. |

---

## Tool budget

The agent enforces a hard cap of **3 tool calls per `answer()` invocation** via `before_tool_callback`. A 4th call returns `{"error": "Tool call budget exceeded (max 3)."}` without raising. The LLM iteration limit is `Settings.max_agent_iterations` (default `3`), wired via `RunConfig(max_llm_calls=…)`.
