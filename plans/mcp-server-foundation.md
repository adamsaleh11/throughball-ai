# Plan: MCP Server Foundation

> Source PRD: docs/prds/03-02-mcp-server-foundation.md

## Architectural decisions

- **Transport**: HTTP+SSE via the official `mcp` Python SDK. FastAPI is the underlying ASGI framework. Uvicorn is the runner.
- **Package layout**: All MCP server source under `src/mcp/`. One file per concern: `server.py`, `registry.py`, `context.py`, `wrappers.py`, `logging.py`, `settings.py`, `tools/`.
- **Validation**: Pydantic v2 for all tool input and output models. Closed schemas matching `docs/contracts/mcp_contracts.md`.
- **Settings**: `pydantic-settings` loading from environment variables and `.env`. Key vars: `AI_API_HOST`, `AI_API_PORT`, `LOG_LEVEL`, `MAX_TOOL_CALLS_PER_REQUEST` (default 5), `APP_ENV`.
- **Telemetry IDs**: Prefixed ULIDs via `python-ulid`. Format: `req_<ulid>`, `tr_<ulid>`, `sp_<ulid>`, `tc_<ulid>`.
- **Trace logging**: `structlog` emitting structured JSON to stdout and appending to `telemetry/traces.jsonl`. Schema follows `docs/contracts/observability.md`.
- **Cache scope**: Per-request `RequestContext` keyed by `request_id`, holding a `dict[(tool_name, input_hash), result]`. Discarded after request completes.
- **Budget behavior**: When `tool_call_count >= MAX_TOOL_CALLS_PER_REQUEST`, return a degraded response (`degraded_reason: TOOL_BUDGET_EXCEEDED`), not an error.
- **Timeout**: `asyncio.wait_for` per tool using contract-specified `timeout_ms`. On timeout, return a degraded response.
- **Retry**: Max 1 retry, 200ms backoff. Retryable only for infrastructure exceptions. Validation errors and business-logic failures are never retried.
- **Stub responses**: `source_type: seeded`. Full contract shape including populated `telemetry` block.
- **Package manifest**: `pyproject.toml` with all dependencies pinned.
- **External APIs**: None. Stub tools return hardcoded seeded fixture data only.

---

## Phase 1: Project scaffold and runnable server

**User stories**: 1, 2, 23

### What to build

Create `pyproject.toml` with all dependencies pinned. Build a typed settings object that reads `AI_API_HOST`, `AI_API_PORT`, `LOG_LEVEL`, `MAX_TOOL_CALLS_PER_REQUEST`, and `APP_ENV` from the environment. Stand up a bare MCP HTTP+SSE server that starts, binds to the configured host and port, and successfully completes the MCP protocol handshake. Update `.env.example` with all new variables. No tools are registered yet.

### Acceptance criteria

- [ ] `pyproject.toml` exists with `mcp`, `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `python-ulid`, `structlog`, `pytest`, `pytest-asyncio`, `httpx` as dependencies.
- [ ] Settings object loads all required env vars with correct types and defaults.
- [ ] `MAX_TOOL_CALLS_PER_REQUEST` defaults to `5` when not set.
- [ ] Server starts without errors using `python -m src.mcp.server` or equivalent entry point.
- [ ] Server binds to `AI_API_HOST:AI_API_PORT`.
- [ ] MCP protocol handshake succeeds (client can connect and receive capabilities).
- [ ] `.env.example` documents all new variables.
- [ ] Test: settings load correctly from env vars including override of default values.
- [ ] Test: server starts and responds to MCP capabilities request.

---

## Phase 2: Request middleware stack

**User stories**: 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18

### What to build

Build the full middleware stack that wraps every tool call, tested against a minimal internal no-op tool (not a user-facing stub). The stack in execution order:

1. **Budget check**: if `tool_call_count >= MAX_TOOL_CALLS_PER_REQUEST`, return degraded response immediately without calling the handler.
2. **Cache check**: compute `sha256(canonical_json(inputs))`, look up `(tool_name, input_hash)` in `RequestContext.cache`. On hit, return cached result with `cache_hit: true`.
3. **Timeout + retry**: wrap the handler with `asyncio.wait_for` using the per-tool `timeout_ms`. On `asyncio.TimeoutError`, return a degraded response. Retry once (200ms delay) for retryable infrastructure exceptions only.
4. **Trace emit**: after the call completes (success, degraded, or error), emit a `tool_call_completed` event to stdout and append to `telemetry/traces.jsonl`. Event must include all fields required by `docs/contracts/observability.md`.

`RequestContext` is created at the start of each request using the `request_id` from the call (or a generated one if absent), and discarded after the response.

### Acceptance criteria

- [ ] `RequestContext` holds `request_id`, `trace_id`, cache dict, and `tool_call_count`.
- [ ] Cache returns a hit on the second call with identical tool name and inputs within the same `RequestContext`.
- [ ] Cache miss on different inputs or different `request_id`.
- [ ] Call that exceeds `MAX_TOOL_CALLS_PER_REQUEST` returns `ok: true`, `degraded: true`, `degraded_reason: TOOL_BUDGET_EXCEEDED` without invoking the handler.
- [ ] Handler that sleeps beyond `timeout_ms` receives a degraded response (tested with a mock slow handler).
- [ ] Handler that raises a retryable exception on the first call and succeeds on the second is invoked exactly twice.
- [ ] Handler that raises a non-retryable exception is invoked exactly once.
- [ ] Every tool call emits a structured JSON event to stdout.
- [ ] Every tool call appends a valid JSON line to `telemetry/traces.jsonl`.
- [ ] Trace event includes: `event_type`, `event_version`, `timestamp`, `environment`, `service`, `request_id`, `trace_id`, `span_id`, `parent_span_id`, `tool_call_id`, `tool_name`, `status`, `source_type`, `cache_hit`, `latency_ms`, `retry_count`, `degraded_mode`, `degraded_reason`.
- [ ] Telemetry IDs use the prefixed ULID format.

---

## Phase 3: `get_match_state` stub tool, end-to-end

**User stories**: 3, 6, 19, 20, 21

### What to build

Introduce the tool registry (explicit `dict[str, ToolDefinition]`) and register the first stub tool. `ToolDefinition` carries the input model class, output model class, handler function, `timeout_ms` (1200), `cacheable` flag, and `max_retry_count` (1). Build the `get_match_state` input model (required `match_id`, optional `include_timeline` defaulting to `false`, optional `allow_external` defaulting to `false`). Build the output model enforcing the full contract response shape including the `telemetry` block. The stub handler returns the seeded World Cup fixture (minute 67, score 2–1, one timeline goal event, `source_type: seeded`). A missing or invalid `match_id` returns the standard `INVALID_INPUT` error envelope. Wire the tool into the running server so it is callable over HTTP.

### Acceptance criteria

- [ ] Tool registry is an explicit dict. Adding a new tool requires only adding an entry to the dict.
- [ ] `get_match_state` is callable over HTTP and returns a response that passes full Pydantic output model validation.
- [ ] Response includes `ok`, `tool`, `source_type`, `data` (with `match_id`, `home_team_id`, `away_team_id`, `status`, `minute`, `score`, `venue_id`, `competition`, `started_at`, `last_updated_at`), and `telemetry`.
- [ ] `telemetry` block includes `trace_id`, `request_id`, `latency_ms`, `cache_hit`, `source_type`, `retry_count`, `degraded`, `external_api_called`.
- [ ] Missing `match_id` returns `ok: false`, `error.code: INVALID_INPUT` in the standard error envelope with a populated `telemetry` block.
- [ ] `include_timeline: true` includes the `timeline` array in `data`.
- [ ] `include_timeline: false` (default) omits `timeline` from `data`.
- [ ] Tool call is logged to `telemetry/traces.jsonl`.
- [ ] Integration test calls `get_match_state` over HTTP and asserts full contract shape.

---

## Phase 4: `get_fan_hotspots` and `search_documents` stub tools

**User stories**: 4, 5, 6, 19, 20, 21

### What to build

Add the two remaining stub tools following the same pattern as Phase 3. `get_fan_hotspots` takes required `city_id`, `match_id`, `team_id`, optional `limit` (default 10) and `include_evidence` (default true). Its seeded response includes one hotspot with `hotspot_id`, `venue_id`, `name`, `neighborhood`, `confidence: medium`, `verified_signals`, `inferred_signals`, `score`, and `evidence_ids`. `search_documents` takes required `query`, optional `filters` object (`city_id`, `match_id`, `team_id`, `document_type`), optional `limit` (default 5) and `include_snippets` (default true). Its seeded response includes one result with `document_id`, `document_type`, `title`, `snippet`, `source_type`, `relevance_score`, and `created_at`. Both tools use `timeout_ms` per contract (`get_fan_hotspots`: 1500, `search_documents`: 1800). Both return standard `INVALID_INPUT` errors for missing required fields.

### Acceptance criteria

- [ ] `get_fan_hotspots` is callable over HTTP and returns a response that passes full Pydantic output model validation.
- [ ] `get_fan_hotspots` response includes `city_id`, `match_id`, `team_id`, `hotspots` array, `computed_at`, and `telemetry`.
- [ ] Each hotspot entry includes `hotspot_id`, `venue_id`, `name`, `neighborhood`, `confidence`, `verified_signals`, `inferred_signals`, `score`, `evidence_ids`.
- [ ] `get_fan_hotspots` missing required field returns `INVALID_INPUT` error envelope.
- [ ] `search_documents` is callable over HTTP and returns a response that passes full Pydantic output model validation.
- [ ] `search_documents` response includes `results` array and `telemetry`.
- [ ] Each result entry includes `document_id`, `document_type`, `title`, `snippet`, `source_type`, `relevance_score`, `created_at`.
- [ ] `search_documents` missing `query` returns `INVALID_INPUT` error envelope.
- [ ] Both tools emit trace log entries to `telemetry/traces.jsonl`.
- [ ] Integration test for each tool asserts full contract shape over HTTP.
- [ ] All three stub tools are listed when querying server capabilities.
