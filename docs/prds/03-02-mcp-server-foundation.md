# PRD: MCP Server Foundation

## Problem Statement

The `throughball-ai` repo has no runnable server yet. Agents cannot call tools, there is no observability surface, and there is no cost enforcement boundary. Without an MCP server, every downstream agent ticket — match analyst, fan gathering, orchestrator — has nowhere to execute tool calls.

The MCP server foundation is the first load-bearing piece of the AI stack. It must be cheap to run, observable by default, and safe against runaway tool loops before any real tool implementations land.

---

## Solution

Build the MCP server foundation: a Python HTTP+SSE server that implements the Model Context Protocol, hosts a typed tool registry with three stub tools, wraps every tool call with timeout, retry, caching, and budget enforcement, and emits structured trace logs on every call.

The server starts locally with a single command, responds to MCP tool calls over HTTP+SSE, and returns valid contract-shaped responses for the three stub tools. Every tool call produces a structured trace log entry. The per-request tool cache prevents duplicate calls within a single agent run. The tool budget prevents uncontrolled loops by returning a degraded response — not an error — when the call limit is reached.

No external APIs are called at this stage. Stub tools return seeded fixture data that matches the full contract response shape defined in `docs/contracts/mcp_contracts.md`.

---

## User Stories

1. As a developer, I want to start the MCP server with a single command, so that I can run it locally without manual setup beyond installing dependencies.
2. As a developer, I want the server to bind to the host and port configured in the environment, so that the same binary works in local, preview, and production environments.
3. As an agent, I want to call `get_match_state` and receive a typed stub response, so that downstream agent logic can be developed before real data sources are wired.
4. As an agent, I want to call `get_fan_hotspots` and receive a typed stub response that includes hotspot candidates with confidence and signal arrays, so that the fan gathering agent can be built against it.
5. As an agent, I want to call `search_documents` and receive a typed stub response with evidence snippets and relevance scores, so that retrieval-based synthesis can be developed immediately.
6. As an agent, I want invalid tool inputs to return a structured `INVALID_INPUT` error, so that I can distinguish user error from infrastructure failure.
7. As an agent, I want every tool call to respect a per-tool timeout, so that a slow or hung tool does not stall the agent indefinitely.
8. As an agent, I want a timed-out tool call to return a degraded response instead of an error, so that the agent can synthesize with available data rather than retrying at the LLM level.
9. As an agent, I want a failed tool call to be retried once for transient infrastructure errors, so that transient failures do not surface to the LLM.
10. As an agent, I want validation errors and business-logic failures to not be retried, so that the retry budget is not wasted on unrecoverable errors.
11. As an agent, I want duplicate tool calls with identical inputs within the same request to return a cached result, so that token cost does not increase from repeated identical lookups.
12. As an agent, I want the cache to be scoped to a single request identified by `request_id`, so that stale results from a previous request never bleed into a new one.
13. As an agent, I want tool calls beyond the per-request budget to return a degraded response with `degraded_reason: TOOL_BUDGET_EXCEEDED`, so that uncontrolled tool loops are stopped without triggering LLM retries.
14. As a developer, I want the tool budget to be configurable via an environment variable, so that I can raise or lower it in different environments without code changes.
15. As a developer, I want every tool call to emit a structured JSON trace log entry, so that I can observe latency, cache hits, retries, and degraded responses in local development.
16. As a developer, I want trace logs to be written to `telemetry/traces.jsonl` as well as stdout, so that I can replay or inspect a session after the fact.
17. As a developer, I want trace log entries to use the shared telemetry schema defined in `docs/contracts/observability.md`, so that future Supabase or OpenTelemetry integration does not require a log schema migration.
18. As a developer, I want every telemetry ID (`request_id`, `trace_id`, `span_id`, `tool_call_id`) to use the prefixed ULID format defined in the observability contract, so that IDs are sortable, unique, and match the contract examples.
19. As a developer, I want stub tool responses to include a fully populated `telemetry` block with realistic field values, so that downstream consumers can be developed against a complete response shape.
20. As a developer, I want input validation to produce clear Pydantic validation errors that map to the `INVALID_INPUT` error code, so that tool schema violations are caught early.
21. As a developer, I want output validation to enforce the contract response shape on every tool response, so that stubs cannot silently omit required fields.
22. As a developer, I want the tool registry to be an explicit dict populated at startup, so that it is easy to inspect, test, and extend without hidden registration side effects.
23. As a developer, I want settings (host, port, log level, tool budget, model name) to be loaded from environment variables via a typed settings object, so that the server is configurable without code changes.

---

## Implementation Decisions

### Transport and Protocol

- MCP server uses HTTP+SSE transport, not stdio. This matches the `AI_API_HOST` and `AI_API_PORT` environment variables and supports multi-agent fan-out.
- The official `mcp` Python SDK handles protocol framing, tool dispatch, and SSE connection management.
- FastAPI is the underlying ASGI framework. Uvicorn is the server runner.

### Directory Structure

- All MCP server source lives under `src/mcp/`.
- Package layout: `src/mcp/server.py` (entrypoint), `src/mcp/registry.py` (tool registry), `src/mcp/context.py` (request context, cache, budget), `src/mcp/wrappers.py` (timeout, retry), `src/mcp/logging.py` (trace logger), `src/mcp/settings.py` (env-backed settings), `src/mcp/tools/` (one file per tool).
- Telemetry output: `telemetry/traces.jsonl` at the repo root.

### Settings

- Loaded via `pydantic-settings` from environment variables and `.env`.
- Key settings: `AI_API_HOST`, `AI_API_PORT`, `LOG_LEVEL`, `MAX_TOOL_CALLS_PER_REQUEST` (default 5), `APP_ENV`.

### Tool Registry

- An explicit `dict[str, ToolDefinition]` populated at module import time in `registry.py`.
- `ToolDefinition` holds: tool name, input model class, output model class, handler function, `timeout_ms`, `cacheable` flag, `max_retry_count`.
- Per-tool timeout values follow the contract: `get_match_state` 1200ms, `get_fan_hotspots` 1500ms, `search_documents` 1800ms.

### Input and Output Validation

- Each tool has a Pydantic v2 `Input` model and a Pydantic v2 `Output` model.
- `Input` models enforce required fields and allowed values per `mcp_contracts.md`.
- `Output` models enforce the full contract response shape including the `telemetry` block.
- Pydantic `ValidationError` maps to the `INVALID_INPUT` error code and the standard error envelope.

### Error Format

- All error responses use the standard error envelope from `mcp_contracts.md`: `ok: false`, `tool`, `error` (with `code`, `message`, `retryable`, `degraded_available`, `details`), and `telemetry`.
- Error codes used by stubs: `INVALID_INPUT`, `TOOL_BUDGET_EXCEEDED`. Real error codes (`MATCH_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`) are reserved for real tool implementations.

### Request Context, Cache, and Budget

- A `RequestContext` object is created at the start of each MCP request, keyed by `request_id`.
- The context holds: `request_id`, `trace_id`, a `cache: dict[tuple[str, str], ToolResult]` keyed on `(tool_name, sha256(canonical_json(inputs)))`, and a `tool_call_count: int`.
- Context is discarded when the request completes. No cross-request state is shared.
- If `request_id` is absent from the call, one is generated and a new context is created.
- When `tool_call_count >= MAX_TOOL_CALLS_PER_REQUEST`, the call returns a degraded response (`ok: true`, `degraded: true`, `degraded_reason: TOOL_BUDGET_EXCEEDED`) without invoking the handler.

### Timeout Wrapper

- `asyncio.wait_for(handler(...), timeout=tool_def.timeout_ms / 1000)`.
- On `asyncio.TimeoutError`, return a degraded response with the appropriate `degraded_reason` per the contract for each tool.

### Retry Wrapper

- Max 1 retry per tool call. 200ms sleep between attempts.
- A call is retryable if the raised exception or returned error code is tagged `retryable: true`. Infrastructure exceptions (connection error, timeout on real tools) are retryable. Validation errors, budget errors, and business-logic failures are not.
- Stub tools are never retried in practice because they do not raise infrastructure exceptions.

### Trace Logging

- `structlog` configured to emit structured JSON.
- Every tool call emits a `tool_call_completed` event matching the observability contract trace payload: `event_type`, `event_version`, `timestamp`, `environment`, `service`, `request_id`, `trace_id`, `span_id`, `parent_span_id`, `agent_run_id`, `tool_call_id`, `agent_name`, `tool_name`, `status`, `source_type`, `cache_hit`, `latency_ms`, `retry_count`, `degraded_mode`, `degraded_reason`.
- Output goes to stdout and appended to `telemetry/traces.jsonl`.

### Telemetry IDs

- All IDs use the prefixed ULID format: `req_<ulid>`, `tr_<ulid>`, `sp_<ulid>`, `tc_<ulid>`.
- `python-ulid` library used for generation.

### Stub Tool Responses

- `get_match_state`: returns seeded match fixture (World Cup match, minute 67, score 2–1, one timeline event) with `source_type: seeded`, `cache_hit: false`, full telemetry block.
- `get_fan_hotspots`: returns seeded hotspot list (one hotspot with verified and inferred signal arrays, `confidence: medium`) with `source_type: seeded`.
- `search_documents`: returns seeded document list (one result with snippet and `relevance_score: 0.84`) with `source_type: seeded`.
- All stubs include a fully populated telemetry block with realistic `latency_ms` and generated IDs.

---

## Testing Decisions

Good tests for this work assert external behavior and contract shapes — not internal implementation details like which dict holds the cache or how the retry counter increments.

### What to test

- **Server start**: the server binds and responds to a health or capabilities request.
- **Stub tool responses**: each of the three stub tools returns a response that passes full Pydantic output model validation (all required fields present, correct types, telemetry block populated).
- **Input validation**: supplying a missing required field or an invalid enum value returns an `INVALID_INPUT` error in the standard error envelope.
- **Cache**: calling the same tool twice with identical inputs in the same `request_id` context returns the same result and emits `cache_hit: true` on the second call.
- **Budget enforcement**: making more than `MAX_TOOL_CALLS_PER_REQUEST` calls in the same context returns a degraded response with `degraded_reason: TOOL_BUDGET_EXCEEDED` on the call that exceeds the limit.
- **Timeout wrapper**: a handler that sleeps beyond the configured timeout receives a degraded response (tested with a mock handler, not real latency waits).
- **Retry wrapper**: a handler that raises a retryable exception on the first call and succeeds on the second is called exactly twice (tested with a mock handler).
- **Non-retryable errors**: a handler that raises a non-retryable exception is called exactly once.
- **Trace log emission**: after calling a stub tool, `telemetry/traces.jsonl` contains a valid JSON line with all required telemetry fields.

### Testing tools

- `pytest` + `pytest-asyncio` for async test cases.
- `httpx` with an ASGI test client for integration-level tool call tests.
- Pydantic model `.model_validate()` for contract shape assertions.
- No mocking of the MCP SDK internals — test through the HTTP interface where possible.

---

## Out of Scope

- Real implementations of `get_match_state`, `get_fan_hotspots`, and `search_documents` (Supabase queries, external API calls).
- Any other tools beyond the three stubs (`get_team_profile`, `get_city_profile`, `get_venues`, `get_city_events`, `generate_itinerary`, `get_route_context`, `create_creator_script`).
- Gemini Flash integration or any model call logic.
- Agent orchestration, routing, or multi-agent coordination.
- Supabase or OpenTelemetry telemetry sinks (local JSONL only).
- Authentication or authorization on the MCP server.
- Deployment or containerization.
- Eval framework.

---

## Further Notes

- The `mcp_contracts.md` schema is treated as the authoritative source of truth for all response shapes. Any deviation in stub output must be treated as a contract violation and fixed before the ticket closes.
- The `observability.md` contract is the authoritative source for all telemetry field names. New field names introduced in this ticket must be added to that contract or documented as a proposed addition.
- The per-request `RequestContext` lifecycle assumes a single MCP session per agent run. If the MCP SDK uses a persistent session across multiple logical requests, the context scoping strategy will need revisiting in a follow-up ticket.
- `MAX_TOOL_CALLS_PER_REQUEST` defaults to 5. This is intentionally conservative for stubs and expected to be tuned upward as real tool latencies are measured.
- Python 3.11+ is required for clean `asyncio.wait_for` timeout handling and modern type hint syntax.
- No package manifest exists in the repo yet. This ticket should produce `pyproject.toml` with all dependencies pinned.
