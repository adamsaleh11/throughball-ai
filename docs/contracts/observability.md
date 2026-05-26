# Observability Contracts

This contract defines the shared telemetry vocabulary for `throughball-ai`. Observability must stay low-cost and orchestration-first: structured JSON logs are the default, local JSON files or Supabase tables are the default storage targets, and paid tracing or metrics platforms are never required.

## Goals

- Give Platform, AI, and Infra the same trace, metric, and eval field names.
- Make every AI request traceable end-to-end across agents, MCP tools, retries, degraded responses, and synthesis.
- Run locally without Datadog, Grafana Cloud, BigQuery, paid tracing tools, or mandatory OpenTelemetry exporters.
- Track latency, retries, degradation, tokens, estimated cost, retrieval usage, citation usage, and eval scores with lightweight payloads.

## Non-Goals

- Full prompt capture.
- Full retrieved document capture.
- Mandatory distributed tracing infrastructure.
- High-cardinality analytics by default.
- Expensive log ingestion or warehouse pipelines.

## Shared Identifiers

Every telemetry event MUST use these identifiers consistently.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `request_id` | string | yes | Stable ID for one user-facing request. All agent runs, tool calls, and final synthesis for the same request share this value. |
| `trace_id` | string | yes | End-to-end trace ID for one orchestration flow. Usually identical in scope to `request_id`, but MAY span retries or async continuation work. |
| `span_id` | string | yes | ID for one timed unit of work, such as orchestration, an agent run, a retrieval step, a model call, or an MCP tool call. |
| `parent_span_id` | string or null | yes | Parent span ID. Use `null` for the root request span. |
| `agent_run_id` | string or null | yes | ID for one agent execution. Use `null` for platform spans that are not agent-owned. |
| `tool_call_id` | string or null | yes | ID for one MCP tool call. Use `null` for non-tool spans. |

IDs SHOULD be opaque, URL-safe strings with stable prefixes, for example `req_01HX`, `tr_01HX`, `sp_01HX`, `ar_01HX`, and `tc_01HX`.

## Standard Event Envelope

All trace, metric, and eval events MUST be structured JSON objects. Implementations MUST NOT log secrets, API keys, full prompts, full completions, full retrieved documents, or private user data beyond stable IDs.

```json
{
  "event_type": "ai_request_completed",
  "event_version": "1.0",
  "timestamp": "2026-05-25T15:30:00Z",
  "environment": "local",
  "service": "throughball-ai",
  "request_id": "req_01HX",
  "trace_id": "tr_01HX",
  "span_id": "sp_01HX",
  "parent_span_id": null,
  "agent_run_id": "ar_01HX",
  "tool_call_id": null,
  "degraded_mode": false,
  "latency_ms": 842,
  "retry_count": 0
}
```

Fields:

- `event_type`: required event name from the event taxonomy below.
- `event_version`: required schema version. Start with `1.0`.
- `timestamp`: required ISO-8601 UTC timestamp.
- `environment`: required deployment name such as `local`, `preview`, or `production`.
- `service`: required service name.
- `degraded_mode`: required boolean. Use `true` when the response used stale, partial, seeded, or fallback data.
- `latency_ms`: required non-negative integer duration for the span or request.
- `retry_count`: required non-negative integer count of retries performed inside the span.

## Event Taxonomy

Allowed `event_type` values:

- `ai_request_started`
- `ai_request_completed`
- `ai_request_failed`
- `agent_run_started`
- `agent_run_completed`
- `agent_run_failed`
- `model_call_completed`
- `tool_call_completed`
- `retrieval_completed`
- `synthesis_completed`
- `eval_completed`

New event types require an update to this contract.

## Trace Payload

Trace events describe one span of work. They are optimized for local JSON logs and Supabase rows, not for verbose tracing backends.

```json
{
  "event_type": "tool_call_completed",
  "event_version": "1.0",
  "timestamp": "2026-05-25T15:30:01Z",
  "environment": "local",
  "service": "throughball-ai",
  "request_id": "req_01HX",
  "trace_id": "tr_01HX",
  "span_id": "sp_tool_01HX",
  "parent_span_id": "sp_agent_01HX",
  "agent_run_id": "ar_fan_gathering_01HX",
  "tool_call_id": "tc_hotspots_01HX",
  "agent_name": "fan_gathering",
  "tool_name": "get_supporter_hotspots",
  "status": "ok",
  "source_type": "cached",
  "cache_hit": true,
  "latency_ms": 46,
  "retry_count": 0,
  "degraded_mode": false,
  "degraded_reason": null
}
```

Trace fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `agent_name` | string or null | yes | Agent name, such as `orchestrator`, `match_analyst`, `fan_gathering`, `city_concierge`, or `itinerary`. |
| `tool_name` | string or null | yes | MCP tool name for tool spans. |
| `status` | string | yes | One of `ok`, `error`, or `degraded`. |
| `source_type` | string or null | yes | One of `seeded`, `cached`, `user_generated`, `external`, or `null` when not data-backed. |
| `cache_hit` | boolean or null | yes | Cache result when applicable. |
| `degraded_reason` | string or null | yes | Machine-readable reason when `degraded_mode` is `true`. |

## Metric Payload

Metric events are compact counters and timings that can be aggregated from JSON logs or inserted directly into Supabase.

```json
{
  "event_type": "model_call_completed",
  "event_version": "1.0",
  "timestamp": "2026-05-25T15:30:02Z",
  "environment": "local",
  "service": "throughball-ai",
  "request_id": "req_01HX",
  "trace_id": "tr_01HX",
  "span_id": "sp_model_01HX",
  "parent_span_id": "sp_agent_01HX",
  "agent_run_id": "ar_match_analyst_01HX",
  "tool_call_id": null,
  "model": "gemini-flash",
  "latency_ms": 620,
  "retry_count": 0,
  "degraded_mode": false,
  "prompt_tokens": 740,
  "completion_tokens": 180,
  "total_tokens": 920,
  "estimated_cost": 0.00012,
  "retrieval_count": 3,
  "citation_count": 2
}
```

Metric fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `model` | string or null | yes | Model identifier. Primary expected value is `gemini-flash`. |
| `prompt_tokens` | integer | yes | Prompt/input token count. Use `0` when no model call occurred. |
| `completion_tokens` | integer | yes | Completion/output token count. Use `0` when no model call occurred. |
| `total_tokens` | integer | yes | Sum of prompt and completion tokens. |
| `estimated_cost` | number | yes | Estimated USD cost for the span or request. Use `0` when no paid model or external service was used. |
| `retrieval_count` | integer | yes | Count of retrieval records used by the span or request. |
| `citation_count` | integer | yes | Count of citations surfaced to the user or downstream synthesis. |

Token and cost tracking MUST be best-effort and lightweight. It MAY use provider usage metadata when available, or deterministic estimates when provider usage metadata is unavailable. The estimator version SHOULD be recorded as `cost_estimator_version` when estimates are not provider-reported.

## Eval Payload

Eval events capture small, structured scores. They must not store full prompts, full outputs, or large evidence blobs.

```json
{
  "event_type": "eval_completed",
  "event_version": "1.0",
  "timestamp": "2026-05-25T15:30:03Z",
  "environment": "local",
  "service": "throughball-ai",
  "request_id": "req_01HX",
  "trace_id": "tr_01HX",
  "span_id": "sp_eval_01HX",
  "parent_span_id": "sp_root_01HX",
  "agent_run_id": "ar_match_analyst_01HX",
  "tool_call_id": null,
  "eval_name": "answer_quality_v1",
  "eval_version": "1.0",
  "latency_ms": 38,
  "retry_count": 0,
  "degraded_mode": false,
  "eval_scores": {
    "groundedness": 0.91,
    "citation_coverage": 0.86,
    "tool_relevance": 0.94,
    "format_compliance": 1.0,
    "cost_efficiency": 0.98
  },
  "passed": true,
  "failure_reasons": []
}
```

Eval fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `eval_name` | string | yes | Stable eval name. |
| `eval_version` | string | yes | Eval version. |
| `eval_scores` | object | yes | Numeric scores from `0.0` to `1.0`. |
| `passed` | boolean | yes | Whether the eval passed configured thresholds. |
| `failure_reasons` | string[] | yes | Machine-readable failure reasons. Empty when passed. |

Standard `eval_scores` keys:

- `groundedness`
- `citation_coverage`
- `tool_relevance`
- `format_compliance`
- `cost_efficiency`

Additional eval score keys require an update to this contract.

## Request Summary Payload

Each user-facing AI request SHOULD emit one compact summary event after completion or failure.

```json
{
  "event_type": "ai_request_completed",
  "event_version": "1.0",
  "timestamp": "2026-05-25T15:30:04Z",
  "environment": "local",
  "service": "throughball-ai",
  "request_id": "req_01HX",
  "trace_id": "tr_01HX",
  "span_id": "sp_root_01HX",
  "parent_span_id": null,
  "agent_run_id": null,
  "tool_call_id": null,
  "route": "match_context",
  "status": "ok",
  "latency_ms": 1420,
  "retry_count": 1,
  "degraded_mode": false,
  "prompt_tokens": 1280,
  "completion_tokens": 420,
  "total_tokens": 1700,
  "estimated_cost": 0.00024,
  "retrieval_count": 5,
  "citation_count": 4,
  "agent_run_count": 2,
  "tool_call_count": 4
}
```

## Storage Defaults

Default storage MUST work locally and cheaply.

Supported storage targets:

- `local_jsonl`: newline-delimited JSON files under a local telemetry directory.
- `supabase`: normalized tables for request summaries, spans, metrics, and evals.
- `opentelemetry`: optional exporter only.

OpenTelemetry exporters MAY be implemented, but they MUST remain optional and disabled by default. The system MUST still run with only local JSON logs.

Recommended local file layout:

```text
telemetry/
  traces.jsonl
  metrics.jsonl
  evals.jsonl
  request_summaries.jsonl
```

## Supabase Table Shape

Supabase storage SHOULD use compact rows with JSON columns for extensibility.

```sql
create table telemetry_request_summaries (
  request_id text primary key,
  trace_id text not null,
  created_at timestamptz not null,
  route text,
  status text not null,
  latency_ms integer not null,
  retry_count integer not null,
  degraded_mode boolean not null,
  prompt_tokens integer not null,
  completion_tokens integer not null,
  total_tokens integer not null,
  estimated_cost numeric not null,
  retrieval_count integer not null,
  citation_count integer not null,
  payload jsonb not null
);
```

```sql
create table telemetry_events (
  id bigserial primary key,
  request_id text not null,
  trace_id text not null,
  span_id text not null,
  parent_span_id text,
  agent_run_id text,
  tool_call_id text,
  event_type text not null,
  timestamp timestamptz not null,
  latency_ms integer not null,
  retry_count integer not null,
  degraded_mode boolean not null,
  payload jsonb not null
);
```

## Sampling

Log sampling MUST be supported to control cost and noise.

Default sampling policy:

- Always log `ai_request_completed`, `ai_request_failed`, and `eval_completed`.
- Always log degraded and error events.
- Sample successful detailed span events with `sample_rate`, default `1.0` locally and configurable in deployed environments.
- When a request is sampled in, all child spans for that `trace_id` SHOULD be sampled in together.
- Request summaries MUST include `sample_rate` when sampling is enabled.

Example:

```json
{
  "sample_rate": 0.25,
  "sampled": true,
  "sampling_reason": "trace_selected"
}
```

## Cost Optimization Rules

- Use structured JSON logs first.
- Do not require Datadog, Grafana Cloud, BigQuery, or paid tracing tools.
- Full OpenTelemetry exporters are optional and disabled by default.
- Default telemetry storage is local JSONL or Supabase tables.
- Log sampling is supported for detailed successful spans.
- Token and cost tracking is lightweight and may use provider metadata or deterministic estimates.
- Store summaries, metrics, and IDs rather than full prompts, full completions, or full retrieved documents.
- Prefer cached retrieval counts and citation counts over verbose evidence logs.
- Do not add eval loops solely to generate observability data.

## End-to-End Trace Requirements

Every AI request MUST produce:

- One root `request_id`.
- One root `trace_id`.
- One root span with `parent_span_id: null`.
- One `agent_run_id` per agent execution.
- One `tool_call_id` per MCP tool call.
- `latency_ms`, `retry_count`, and `degraded_mode` for every event.
- Token and cost totals on every model call and final request summary.
- Retrieval and citation counts on retrieval, synthesis, model, and final request summary events where applicable.
- Eval scores for configured eval runs.

## Acceptance Criteria

- Platform, AI, and Infra use the same telemetry vocabulary in this contract.
- Every AI request can be traced end-to-end from request to agent runs, MCP tool calls, model calls, synthesis, and evals.
- Telemetry runs locally using structured JSON logs without paid services.
- Supabase can be used as the default shared storage option without requiring a warehouse.
- Optional OpenTelemetry exporters can be added without changing required event payloads.
