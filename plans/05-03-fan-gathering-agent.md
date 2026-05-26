# Plan: Fan Gathering Agent

> Source PRD: `docs/prds/05-03-fan-gathering-agent.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no new HTTP route is required for this slice; the stable public surface is an async Fan Gathering Agent interface.
- **Schema**: agent request supports city, match, optional team, optional natural-language question, date window, and output length cap; agent response includes answer, confidence, evidence summary, verified signals, inferred signals, confidence details, tool sources, degraded state, and telemetry.
- **Key models**: Fan Gathering Agent, Gemini Flash synthesis adapter, deterministic confidence result, seeded MCP responses for venues and city events.
- **Auth**: no authentication or authorization changes.
- **External services**: MCP tools use cached/seeded data with `allow_external: false`; production synthesis supports Gemini Flash only, while tests use deterministic or mocked synthesis.
- **Safety**: cached or seeded data must never be described as live real-time certainty.
- **Cost controls**: one request uses at most three logical MCP tool calls, Gemini Flash only, short configurable output length, and compact telemetry.

---

## Phase 1: Seed the Required MCP Tool Surface

**User stories**: 9, 10, 13, 23

### What to build

Add the missing MCP fan-intelligence tools so the agent can call the full required tool set through the existing MCP boundary. The new tools return small seeded or cached city events and venue records shaped according to the existing MCP contracts, with telemetry and source attribution consistent with the current MCP server behavior.

### Acceptance criteria

- [ ] `get_city_events` is registered with the MCP server and returns seeded/cached contract-shaped event data.
- [ ] `get_venues` is registered with the MCP server and returns seeded/cached contract-shaped venue data.
- [ ] Both tools reject missing required inputs with the standard `INVALID_INPUT` error envelope.
- [ ] Both tools default to no external API access and report `external_api_called: false`.
- [ ] Existing MCP tool tests continue to pass.

---

## Phase 2: Add the Fan Gathering Agent Contract

**User stories**: 1, 2, 3, 8, 14, 15, 24

### What to build

Introduce the Fan Gathering Agent public interface and response contract. The first vertical slice should accept a natural fan question or structured team input, resolve simple team aliases deterministically, and return a short bounded answer shape that downstream callers can depend on.

### Acceptance criteria

- [ ] The agent accepts structured city and match inputs with either `team_id` or supported natural-language team aliases.
- [ ] Supported aliases such as Argentina, Brazil, and Canada resolve without LLM parsing.
- [ ] Unknown team aliases are handled safely without making unsupported certainty claims.
- [ ] The response shape includes answer text, confidence, evidence summary, verified signals, inferred signals, tool sources, degraded state, and telemetry.
- [ ] Output length respects a configurable cap.

---

## Phase 3: Implement Bounded Tool Orchestration

**User stories**: 9, 11, 12, 13, 23

### What to build

Wire the agent to the three required MCP tools with one bounded fan-intelligence lookup. Calls run concurrently with isolated failure handling so that one timeout, exception, or degraded result does not discard successful data from the other tools. The agent records compact source attribution for each tool result.

### Acceptance criteria

- [ ] One fan gathering answer attempts no more than three logical tool calls.
- [ ] The agent calls `get_fan_hotspots`, `get_city_events`, and `get_venues`.
- [ ] All tool calls force `allow_external: false`.
- [ ] Tool failures or degraded responses are isolated and reflected in the final degraded state.
- [ ] Tool source attribution includes tool name, source type, degraded state, and external-call status.

---

## Phase 4: Add Confidence and Safety Synthesis

**User stories**: 4, 5, 6, 7, 16, 17, 18

### What to build

Add deterministic confidence calculation and conservative answer synthesis over the MCP results. The agent preserves verified and inferred signals, exposes confidence contributors and downgrade reasons, and avoids phrasing cached or seeded data as live certainty.

### Acceptance criteria

- [ ] Confidence is computed deterministically from inspectable tool-result inputs.
- [ ] Confidence details include contributors and downgrade reasons.
- [ ] Verified and inferred signals remain separate in the final response.
- [ ] Low-confidence cases return cautious wording and explain the data limitation.
- [ ] Seeded/cached data is described as suggested or listed, never as current live crowd activity.
- [ ] Backend hotspot order is preserved and the agent does not calculate hotspot scores.

---

## Phase 5: Wire Gemini Flash Adapter Path and Agent Telemetry

**User stories**: 19, 20, 21, 22

### What to build

Add the production synthesis adapter boundary for Gemini Flash while keeping deterministic synthesis available for tests. Route synthesis through the existing model router, forbid Gemini Pro, and emit compact agent telemetry suitable for local observability without logging full prompts or completions.

### Acceptance criteria

- [ ] The production synthesis adapter path supports Gemini Flash route metadata.
- [ ] Tests can run with deterministic or mocked synthesis without live Gemini or Vertex credentials.
- [ ] The agent-selected model is Gemini Flash and no Gemini Pro model is introduced.
- [ ] Agent telemetry includes agent name, logical tool call count, selected model, degraded state, and confidence state.
- [ ] Telemetry avoids full prompt text, completion text, large evidence dumps, secrets, and private user data.

---

## Phase 6: Acceptance and Regression Coverage

**User stories**: 1-24

### What to build

Close the slice with behavior-level regression coverage for the representative fan questions and failure modes. Tests should verify public behavior through the agent interface and MCP server calls, not private helper details.

### Acceptance criteria

- [ ] A request for Argentina fan gathering returns a short grounded answer with confidence and evidence summary.
- [ ] A request for Brazil watch-location support works through deterministic alias parsing.
- [ ] A fan-zone question uses cached/seeded event data without live-certainty wording.
- [ ] Empty, degraded, or mostly inferred data yields low-confidence safe output.
- [ ] The full relevant test suite passes without live Gemini, Vertex, external APIs, or network-only dependencies.
