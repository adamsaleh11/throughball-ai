# PRD: City Concierge Agent (03-05)

## Problem Statement

Users visiting a city need personalized, trustworthy recommendations across five key areas: restaurants, nightlife, tourism, fan events, and local gems. Current fan-gathering agent answers only sports-specific questions ("where are fans gathering?"). There's no general-purpose concierge to explore "what should I do in Paris for 3 days?" with adaptive recommendations that respect user context (budget, dietary preferences, time constraints, interests) and cite reliable sources. Existing systems either rely on live APIs (cost, latency, external dependency) or lack structured reasoning with confidence signals and transparent source attribution.

**Why now**: The fan-gathering agent (03-04) proved the ADK + RAG pattern works; the RAG service (09-01) is implemented and stable; we have cost-efficient Flash pricing and session management in place. Building on this foundation gives users a complete companion app experience without new infrastructure.

## Solution

Build **CityConciergeAgent** as an ADK LlmAgent wrapper (mirroring fan_gathering_adk.py) that:

1. **Understands context** via `get_city_profile` (city landmarks, neighborhoods, vibe)
2. **Discovers venues** via `get_venues` (restaurants, bars, museums, events)
3. **Learns what's happening** via `get_city_events` (concerts, sports, fan events, festivals)
4. **Grounds answers** via `search_documents` (retrieves up to 5 curated knowledge chunks per search, cites sources inline)
5. **Adapts to user preferences** (budget, dietary, time, interests) extracted from the query
6. **Returns structured responses** (answer text + confidence + citations + reasoning + metrics)
7. **Operates within constraints** (max 4 tool calls, Flash model only, no live external APIs, multi-turn session dedup)

The agent synthesizes recommendations that:
- Mix across 5 responsibility areas (not all restaurants if user asks broadly)
- Include reasoning ("museum is 15min walk, has impressionist collection")
- Cite sources inline ([1] = museum page, [2] = restaurant review)
- Surface confidence labels (high/medium/low based on retrieval quality + citations + tool diversity)
- Emit cost/latency metrics for operational tracking

## User Stories

### Context & Preferences (Parsing)

1. As a visitor asking "What should I do in Paris for 3 days?", I want the agent to extract that I'm time-constrained and want variety, so recommendations are paced (Day 1, Day 2, etc.) and span multiple categories.

2. As a vegetarian visitor asking "Restaurants in the Marais, vegetarian only, under €50", I want my dietary constraint applied to all recommendations, so I don't get dairy-heavy or fish dishes.

3. As a user saying "I love art and nightlife", I want my interests to weight recommendations toward art museums + galleries + late-night bars, so results feel personalized not generic.

4. As a user asking "What's fun tonight?", I want the agent to understand my temporal context (now, this evening) and prioritize events + nightlife, so answers are relevant.

### Exploration & Adaptation (Tool Use)

5. As a user asking "Best restaurants in the Marais?", I want the agent to call `get_city_profile` (understand Marais neighborhood) + `search_documents` (find curated restaurants), so I get contextual recommendations, not just a list.

6. As a user asking "What events are happening this week?", I want the agent to call `get_city_events` first, so I see concerts, festivals, sports matches, fan gatherings all in one answer.

7. As a user asking "I have 2 hours free, where can I go?", I want the agent to skip slow-experience venues and prioritize nearby/quick activities, so recommendations fit my time.

8. As a user who previously asked "Museums in Paris", then asks "Tell me more about the Louvre", I want the agent to reuse prior retrieval results from my session, so the second answer is fast and costs less.

9. As a user asking a vague question like "What's cool in Paris?", I want the agent to prioritize 4 recommendation categories (restaurants, nightlife, tourism, local gems, events) with 1-2 items each, so I get balanced breadth.

10. As a user asking "More nightlife options?", I want the agent to start a fresh tool-call budget (4 calls available), so refinement doesn't feel constrained.

### Grounding & Safety (Citations & Confidence)

11. As a user reading "Le Comptoir du Relais [1] is excellent for French classics", I want [1] to link to a real source (document path, title), so I can verify the recommendation.

12. As a user asking "Is the Louvre open on Mondays?", I want the agent to either cite a source [1] or decline ("I don't have current hours, consult official website"), so I don't get false information.

13. As a user reading recommendations, I want a confidence label (high/medium/low) showing how certain the agent is, so I know whether to trust the answer or ask for refinement.

14. As a system operator, I want every response to include metrics (tokens_per_second, cost_per_request, tool_call_count), so I can track cost and detect performance regressions.

15. As a user asking something the agent can't answer well ("Where will the 2030 World Cup be held?"), I want a low-confidence fallback: "I don't have reliable information. Consult official sources.", so I'm not misled.

### Multi-Turn Conversations (Sessions)

16. As a user in a 10-minute conversation, I want prior recommendations and my extracted preferences to stay in context, so the agent doesn't re-ask "Are you vegetarian?" every turn.

17. As a user asking the exact same question twice in one session, I want the system to reuse retrieval results, so the second answer is instant and costs zero extra tokens.

18. As a user asking the same question in a different city, I want a fresh session, so Paris recommendations don't leak into London queries.

19. As a user in a multi-turn conversation, if the agent uses 3 of 4 available tools, I want the answer to note "I can search more in a follow-up turn" rather than silently cutting off.

### Degradation & Error Cases

20. As a user asking about events in a city with no events scheduled, I want the agent to say "No major events this week, but here are top venues to visit:" rather than making up events.

21. As a user asking about a city where no venues match my constraints (e.g., "fine dining in a tiny village"), I want the agent to clarify ("I found casual restaurants, not fine dining") or offer nearby alternatives.

22. As a user asking a query where retrieval returns zero chunks, I want the fallback answer: "I don't have enough reliable information. Consult official sources."

23. As a developer integrating this agent, I want to know it will never call a tool beyond the 4-call budget, so I can safely expose it in production.

24. As a system operator, I want degraded runs (tool failure, zero retrieval, ungrounded answer) flagged in metrics, so I can monitor quality trends.

### Integration & Ecosystem

25. As a user of the app, I want to ask the fan-gathering agent a question, then ask the concierge agent a follow-up, with both using the same session_id, so context flows smoothly.

26. As a developer, I want the CityConciergeAgent to follow the same interface pattern as FanGatheringADKAgent, so onboarding is fast and future agents are consistent.

27. As an operator, I want response times under 1 second per turn (Flash latency + retrieval latency), so the UX feels snappy.

28. As a developer, I want the agent to accept `stub_model`, `mcp_factory`, `session_service`, `retrieval_service`, and `synthesis_adapter` for testability, so all tests are fast and never hit production APIs.

---

## Implementation Decisions

### Modules to Build or Modify

**New modules**:
- `src/throughball_ai/agents/city_concierge_adk.py` — Main CityConciergeADKAgent class (mirroring FanGatheringADKAgent)
  - Wraps google.adk.agents.LlmAgent
  - Manages tool lifecycle (get_city_profile, get_venues, get_city_events, search_documents)
  - Enforces 4-call budget via before_tool_callback
  - Applies safety post-processing (banned phrases, citation validation)
  - Emits metrics to telemetry/agent_runs.jsonl

**Modified modules**:
- `src/throughball_ai/mcp/tools/` — Verify all 4 required tools exist and are wired correctly
  - `get_city_profile.py` — Already exists (03-04); reuse as-is
  - `get_venues.py` — Already exists; extend if needed for filtering (venue_type, price_tier, etc.)
  - `get_city_events.py` — Already exists; ensure fan_events category is included
  - `search_documents.py` — Already exists; ensure it hits the RAG service (09-01)

- `src/throughball_ai/adk/callbacks.py` — Already wired; no changes needed (reuse existing callback hooks)

- `src/throughball_ai/telemetry/agent_metrics.py` — Already exists from 08-02; reuse RunMetricsAccumulator

- `src/throughball_ai/agents/__init__.py` — Add CityConciergeADKAgent to AGENT_NAMES if it exists; ensure it's importable

### Tool Interfaces (Contracts)

**Tool: `get_city_profile`**
```
Input: { city_id: str, [team_id: str] }
Output: { 
  city: str, 
  neighborhoods: [{ name, vibe, landmarks }], 
  transport: { description }, 
  demographics: { vibe_keywords },
  ok: bool, 
  telemetry: { source_type, latency_ms }
}
```

**Tool: `get_venues`**
```
Input: { city_id: str, [venue_type: str], [allow_external: bool] }
Output: { 
  venues: [{ id, name, type, description, neighborhood, price_tier, hours }], 
  ok: bool, 
  telemetry: { source_type, latency_ms }
}
```

**Tool: `get_city_events`**
```
Input: { city_id: str, [start_date: str, end_date: str], [category: str], [allow_external: bool] }
Output: { 
  events: [{ id, name, date, time, category, description, location }], 
  ok: bool, 
  telemetry: { source_type, latency_ms }
}
```

**Tool: `search_documents`**
```
Input: { query: str, city_id: str, [team_id: str], [category: str], [top_k: int], [allow_external: bool] }
Output: { 
  chunks: [{ id, text, source_path, title, confidence }], 
  confidence: "high" | "medium" | "low" | "none",
  ok: bool, 
  telemetry: { source_type, latency_ms }
}
```

### Agent Response Contract

```
{
  "answer": str,                      // User-facing recommendation text
  "confidence": "high" | "medium" | "low",
  "citations": [
    { id: int, source_path: str, title: str }
  ],
  "grounded": bool,                   // All claims have [N] citations
  "tool_sources": [str],              // ["get_city_profile", "search_documents", ...]
  "recommendations": [
    { category: str, items: [str], reasoning: str }
  ],
  "model_name": str,                  // e.g., "gemini-2.0-flash-001"
  "metrics": {
    "tool_call_count": int,
    "total_latency_ms": int,
    "tool_latencies": { tool_name: ms },
    "prompt_tokens": int,
    "completion_tokens": int,
    "tokens_per_second": float,
    "cost_per_request": float,
    "confidence_label": str,
    "degraded": bool
  }
}
```

### Safety & Post-Processing

**Banned phrases** (inherited from fan-gathering agent, adapted):
- No freshness claims ("currently", "right now", "live", "confirmed gathering", "are there now")
- Reason: Data is seeded/cached/static, not real-time.

**Citation validation**:
- Every recommendation must cite a source [N] where N ≤ number of retrieved chunks.
- If answer contains unsupported claims (no citations), set `grounded=false` and confidence to "low" or fallback.

**Confidence computation**:
- High: retrieval_confidence ≥ "high" + citations present + ≥2 tools called
- Medium: partial evidence (1-2 chunks, citations, or single tool)
- Low: no sources, no citations, or zero retrieval

**Fallback answer** (when grounding fails):
```
"I don't have enough reliable information to answer that. 
Try a more specific question, or consult official sources."
```

### Model & Constraints

- **Model**: Gemini 2.0 Flash (gemini-2.0-flash-001) or later (never Pro)
- **Max output tokens**: 512 (from Settings.max_output_tokens)
- **Temperature**: 0.2 (deterministic recommendations, low hallucination)
- **Max tool calls**: 4 per turn (enforced by before_tool_callback in session state)
- **Max retrieved chunks per search**: 5 (enforced by RagAnsweringService top_k=5)
- **Max context chars**: 5 chunks × 1000 chars = 5000 chars (hard cap in prompt_builder)
- **Answer length**: No hard cap (but aim for 300-800 chars for readability)

### Session Management

- **Session storage**: InMemorySessionService (from ADK runner)
- **Dedup key**: (session_id, normalized_query) — lowercase + strip
- **State lifecycle**: Per-turn for tool_call_count (resets), per-session for retrieval cache (persists)
- **Multi-turn support**: Recommendations log + user_context appended to subsequent prompts
- **Session timeout**: Implementation detail (likely 30 min idle for test instances)

### Metrics & Observability

- **Emitter**: RunMetricsAccumulator from telemetry/agent_metrics.py (existing)
- **Output**: Newline-delimited JSON to telemetry/agent_runs.jsonl
- **Fields**: agent_run_id, session_id, trace_id, request_id, prompt_tokens, completion_tokens, total_tokens, tokens_per_second, estimated_cost, cost_per_request, tool_call_count, tool_latencies, retries, degraded, final_confidence, latency_ms
- **Privacy**: No full user queries or document bodies in logs; only chunk IDs and source paths

### System Instruction

The LLM receives a system prompt instructing:
1. "You are a city concierge for the Throughball app. Answer questions about restaurants, nightlife, tourism, fan events, and local recommendations."
2. "You have access to 4 tools. Call them strategically to understand the city and find the best recommendations."
3. "Tool budget: 4 calls per turn. Prioritize depth over breadth."
4. "Always cite your sources using [N] where N is the chunk ID."
5. "Never make claims without a source. If you don't have enough information, use the fallback: 'I don't have enough reliable information...'"
6. "Distinguish verified signals (venue ratings, event dates) from inferred signals (proximity, atmosphere)."
7. "Adapt recommendations to user context: budget, dietary preferences, time, interests."

---

## Testing Decisions

### What Makes a Good Test

- **Test external behavior**: Does the agent return well-structured responses with correct confidence, citations, and metrics?
- **Test contracts, not implementation**: Verify response shape and field values; don't test internal state mutations.
- **Mock at the boundary**: Inject fake RetrievalService, FakeSynthesisAdapter, FakeMcpServer; never patch globals or internal methods.
- **No live API calls**: All tests must complete in < 2 seconds with deterministic outputs.
- **Use caplog for callbacks**: Capture and assert telemetry emitted to JSONL (mirrors test_adk_runtime.py pattern).

### Modules with Explicit Test Coverage

**CityConciergeADKAgent**:
- Happy path: query + valid tool results → correct answer, confidence="high", citations present
- Tool budget enforcement: 4th tool call is blocked with error
- Safety post-processing: banned phrases set degraded=true, unsupported claims trigger fallback
- Multi-turn dedup: same query twice in same session reuses retrieval (verify retrieval_service.call_count==1)
- Degraded tool: get_city_events throws → partial response with degraded=true
- Zero retrieval: search_documents returns empty → fallback answer, confidence="none"
- Metrics emission: response includes tool_latencies, tokens_per_second, cost_per_request, degraded flag

**Tool Integration** (verify existing tools work with the agent):
- get_city_profile returns expected schema with ok=true
- get_venues returns venue list with neighborhood + price_tier
- get_city_events includes fan_events category
- search_documents returns chunks with source_path + title

**Safety & Confidence** (unit tests for post-processor):
- Confidence computation: (retrieval="high" + citations + 2 tools) → "high"
- Confidence computation: (retrieval="none") → "low"
- Citation validation: answer with [1] where chunk 1 exists → grounded=true
- Citation validation: answer with no [N] → grounded=false, confidence lowered
- Banned phrase detection: "are there now" in answer → degraded=true, degraded_reason populated

### Prior Art (Test Patterns)

- `tests/test_fan_gathering_adk_agent.py` — Stub LLM, mcp_factory injection, no live API calls
- `tests/test_adk_runtime.py` — AdkCallbackHooks, RunMetricsAccumulator, JSONL writer tests
- `tests/test_rag_service.py` — FakeRetrievalService, FakeSynthesisAdapter, session dedup
- `tests/mcp/test_trace.py` — JSONL emission, injected writer

---

## Out of Scope

- **Real-time integrations**: No live Google Places API, no real-time event feeds. All knowledge is pre-curated and batched.
- **User profiles & personalization history**: The agent learns preferences from the current query only; no persistent user model or recommendation history across sessions.
- **Multilingual support**: All system instructions, fallbacks, and responses are in English.
- **Image/map responses**: Agent returns text recommendations only; no embedded maps or photos.
- **Payment/booking**: No integration with reservation systems, ticket sales, or payment processors.
- **Admin workflows**: No dashboard for editing knowledge base, no moderation UI for venue ratings.
- **Supabase integration for metrics**: Metrics are written to JSONL only; Supabase writer (mentioned in 08-02) is out of scope.
- **Advanced reasoning patterns**: No multi-hop reasoning ("Where can I eat after watching this event?"), no complex constraint solving.
- **Fan-gathering agent changes**: This PRD does not modify the existing fan-gathering agent; it coexists as a separate service.

---

## Further Notes

### Assumptions

1. All 4 required tools (get_city_profile, get_venues, get_city_events, search_documents) are already implemented and wired in the MCP layer.
2. The RAG service (RagAnsweringService) is stable and ready for use; search_documents is its thin MCP wrapper.
3. InMemorySessionService is available and supports the dedup cache pattern (already tested in 09-01).
4. Gemini 2.0 Flash is available via the ModelRouter; cost estimation is via telemetry/costs.py.
5. The fan-gathering agent pattern (LlmAgent + before_tool_callback + post-processing + metrics) is the canonical reference; this agent follows it closely.

### Rollout & Dependencies

1. **Dependency**: Requires 03-03 (RAG service) + 03-04 (fan-gathering agent pattern) + 08-02 (metrics accumulator) to be merged.
2. **Rollout**: Phase 1 (agent scaffold + tool wiring), Phase 2 (budget + degradation), Phase 3 (metrics), Phase 4 (post-processing + smoke test), Phase 5 (cleanup + migration if needed).
3. **API exposure**: Once agent is built, wire it to a REST endpoint (e.g., `POST /agent/city-concierge`); frontend can call it alongside fan-gathering agent.
4. **Monitoring**: After launch, track cost/latency/confidence via telemetry/agent_runs.jsonl; set up alerts for degraded runs (degraded=true > 5%).

### Open Questions

1. Should CityConciergeAgent support team_id (for fan events filtering) in the same way fan-gathering does? Assume yes for now (can be optional parameter).
2. What's the session timeout in production (30 min, 1 hour, infinite)? Not specified here; defaults to ADK runner's InMemorySessionService behavior.
3. Should the knowledge base include user-generated content (reviews)? Assume no for v1 (curated only); user content can be added in follow-up.

### Follow-Up Work

1. **Personalization v2**: Build a user preference model (past queries, favorite categories) to weight recommendations further.
2. **Real-time events**: Integrate live event feeds (Spotify, Ticketmaster) once cost model allows.
3. **Multi-hop reasoning**: Enable "Show me the best restaurant within walking distance of the Louvre."
4. **Supabase writer**: Implement metrics writer from 08-02 so runs are queryable in Postgres.
5. **Image generation**: Add optional hero image per recommendation via Imagen or similar.

