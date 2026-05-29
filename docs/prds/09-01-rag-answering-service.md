# PRD: RAG Answering Service (09-01)

## Problem Statement

ADK agents currently answer questions using structured tool results from the MCP layer (hotspots, venues, events). These tools return typed, enumerable data well-suited to deterministic synthesis. They do not tap the vector-indexed knowledge corpus — the seeded city overviews, fan hotspot narratives, team profiles, and matchday guides ingested in Phase 2.

When an agent needs to answer a free-text question backed by document evidence, there is no reusable path from query to grounded, cited answer. Each new agent would have to re-implement: how to call `search_documents`, how to format retrieved chunks into an LLM prompt, how to verify that the final answer actually cites something, and how to avoid re-fetching the same evidence in the same session. The lack of this shared layer is the blocker for building any agent that relies on document-level knowledge rather than structured API data.

## Solution

Build a reusable RAG answering service in `src/throughball_ai/rag/` that any ADK agent can call with a query and receive a grounded, cited answer backed by retrieved document chunks. The service:

1. Retrieves the top-k most relevant chunks from the knowledge corpus via `RetrievalService`, with session-level deduplication to avoid redundant retrieval for the same query.
2. Builds a compact, bounded grounded context from those chunks, formatted for injection into an LLM prompt.
3. Synthesizes an answer using Gemini Flash only.
4. Evaluates groundedness heuristically — checking that the answer cites retrieved evidence and that retrieval confidence is not below a safe threshold.
5. Extracts citations from the answer and returns them as a structured list alongside the answer text.
6. Returns a typed `RagAnswer` with `answer`, `confidence`, `citations`, `grounded`, `groundedness_reason`, `chunk_ids_used`, and `degraded` fields.

Agents call one method — `RagAnsweringService.answer(query, session_id, ...)` — and receive a complete, ready-to-return result. The four internal modules (`retriever`, `prompt_builder`, `grounding`, `citations`) are implementation details hidden behind that interface.

## User Stories

1. As an ADK agent, I want to call a single `answer()` method with a query and session ID, so that I receive a complete grounded answer without implementing retrieval, prompting, or grounding logic myself.

2. As an ADK agent, I want the service to cache retrieved chunks for the same query within a session, so that repeated calls with the same question do not trigger redundant Vertex embedding and vector search calls.

3. As an ADK agent, I want chunk IDs and short summaries stored in ADK session state after retrieval, so that the session record reflects what evidence was consulted without storing raw full document text.

4. As an ADK agent, I want the answer to include inline citation markers (e.g. `[1]`, `[2]`) that map to retrieved source paths, so that callers can render or audit the evidence trail.

5. As an ADK agent, I want to receive a separate `citations` list alongside the answer text, so that I can present source attribution to downstream consumers without re-parsing the answer string.

6. As an ADK agent, I want the service to return a safe low-confidence answer when `retrieval_confidence` is `"none"` or when no chunks are cited in the answer, so that the agent never surfaces unsupported claims as if they were grounded.

7. As an ADK agent, I want the grounded context injected into the LLM prompt to be bounded in size, so that I do not inadvertently blow context budgets or incur excessive token costs.

8. As a system operator, I want the service to use Gemini Flash only — never Gemini Pro or any LLM reranker — so that synthesis costs remain predictable.

9. As a system operator, I want the service to default to `top_k=5` for retrieval, so that the cost and latency floor is well-defined and consistent across agents unless explicitly overridden.

10. As an agent developer, I want to inject a fake `RetrievalService` in tests, so that I can verify RAG behavior — citation extraction, low-confidence fallback, session dedup — without needing a live Supabase or Vertex connection.

11. As an agent developer, I want the `RagAnswer` return type to be a typed dataclass, so that I can access fields without dict-key guessing and benefit from static analysis.

12. As an agent developer, I want query normalization in the session dedup cache (lowercase, strip whitespace), so that minor variations in the same question do not trigger redundant retrieval.

13. As an ADK agent, I want the grounding check to verify that the answer contains at least one inline citation matching a retrieved source, so that answers that drift beyond the evidence are flagged as ungrounded before being returned.

14. As an ADK agent, I want the safe fallback answer to be a fixed, non-speculative string, so that low-confidence responses never contain hallucinated content.

15. As an agent developer, I want the RAG service to be stateless with respect to the retrieval client, so that the same `RagAnsweringService` instance can serve multiple sessions concurrently without cross-session cache pollution.

## Implementation Decisions

### Modules

**`retriever.py`** — `Retriever` class. Wraps `RetrievalService` (injected, not constructed internally). Maintains a `_query_cache: dict[str, list[dict]]` per-instance, keyed by `(session_id, normalized_query)` where normalization is lowercase + stripped. On a cache hit for the same session + query, returns cached chunks without re-embedding. On a cache miss, calls `RetrievalService.search()` directly (no MCP layer). After retrieval writes compact retrieval refs (`chunk_id`, `source_path`, short `summary`) to `InMemorySessionService.add_retrieval_reference()`. Enforces `top_k` ≤ 8 (existing `MAX_TOP_K` constant).

**`prompt_builder.py`** — Pure function `build_grounded_context(chunks, source_paths, titles) -> str`. Renders chunks as numbered XML-style source blocks:
```
<source id="1" path="knowledge/...">
chunk text
</source>
```
Hard cap: total context string is capped at `top_k × MAX_CHUNK_CHARS` characters (default 5 × 1000 = 5,000 chars). Excess chunks are dropped, not truncated mid-block. Returns the formatted string for direct injection into a synthesis prompt.

**`grounding.py`** — `GroundingEvaluator`. Heuristic-only, no LLM calls. Evaluates: (1) `retrieval_confidence` from `RetrievalService` results — if `"none"`, immediately ungrounded; (2) citation presence — checks whether the answer string contains at least one `[N]` marker where `N` corresponds to a retrieved chunk. Returns `grounded: bool` + `groundedness_reason: str`.

**`citations.py`** — Pure function `extract_citations(answer, source_paths, titles) -> list[dict]`. Regex-scans the answer for `[N]` markers, maps each N to the corresponding `source_path` and `title` from the retrieval result, returns `[{"id": N, "source_path": "...", "title": "..."}]`. Markers referencing out-of-range IDs are silently dropped.

**`RagAnsweringService`** (entry point, in `__init__.py` or `service.py`) — Orchestrates: `Retriever.retrieve()` → `prompt_builder.build_grounded_context()` → Flash synthesis → `GroundingEvaluator.evaluate()` → `citations.extract_citations()`. Exposes a single async method `answer(query, session_id, *, city_id, team_id, category, top_k) -> RagAnswer`. The Flash synthesis call is isolated in an injectable adapter (mirroring `GeminiFlashSynthesisAdapter` in `fan_gathering.py`) so tests never hit the live model.

### Return Type

```python
@dataclass
class RagAnswer:
    answer: str
    confidence: str          # "high" | "medium" | "low" | "none"
    citations: list[dict]    # [{"id": int, "source_path": str, "title": str}]
    grounded: bool
    groundedness_reason: str
    chunk_ids_used: list[str]
    degraded: bool
```

### Low-Confidence Fallback

Triggered when `retrieval_confidence == "none"` OR `grounded == False`. Returns a fixed answer string: `"I don't have enough reliable information to answer this confidently. Please consult official matchday sources."` with `confidence="none"`, `grounded=False`, and an empty `citations` list.

### Session State Contract

Only `chunk_id`, `source_path`, and a short `summary` (≤ 120 chars, first sentence of the chunk) are stored in `retrieval_refs`. Full chunk text is never written to session state.

### Flash-Only Constraint

`RagAnsweringService` routes synthesis through `ModelRouter.route(agent_name)`, which returns the Flash model. An assertion guards against Pro model selection at construction time, matching the guard in `GeminiFlashSynthesisAdapter`.

### Dependencies on Existing Modules

- `RetrievalService` and `MAX_CHUNK_CHARS` from `retrieval/documents.py`
- `InMemorySessionService` from `adk/session_service.py`
- `ModelRouter` from `model_router/router.py`
- `Settings` / `get_settings` from `config/settings.py`

No MCP server dependency. No changes to `search_documents` tool.

## Testing Decisions

**What makes a good test here:** test the contract of `RagAnsweringService.answer()` and each module's public function/method using injected fakes. Do not test Flash synthesis directly — isolate it behind an adapter and stub it in tests. Do not reach Supabase or Vertex.

**Prior art:** `tests/test_document_retrieval.py` provides `FakeEmbeddingProvider` and `FakeVectorSearchRepository` injected at the `RetrievalService` boundary. `tests/test_fan_gathering_agent.py` shows how to fake MCP tool results and drive an agent to completion. Mirror both patterns.

**Coverage required:**

- `Retriever`: cache hit returns same chunks without re-calling `RetrievalService`; cache miss calls retrieval and writes refs to session; `top_k` is clamped to 8; degraded retrieval returns empty chunks and sets `degraded=True`.
- `build_grounded_context`: output is bounded at `top_k × MAX_CHUNK_CHARS`; excess chunks are dropped; XML format is correct.
- `GroundingEvaluator`: `retrieval_confidence="none"` → ungrounded; no `[N]` citation in answer → ungrounded; answer with valid citation → grounded.
- `extract_citations`: `[1]` and `[2]` markers map correctly to source paths; out-of-range marker is dropped; empty answer returns empty list.
- `RagAnsweringService.answer()` integration (with fake retrieval + fake synthesis adapter): citation path, low-confidence fallback path, session dedup reuse path, bounded context path.

All tests use `@pytest.mark.asyncio`. No `unittest.mock.patch` on module globals — inject fakes through constructors.

## Out of Scope

- LLM-based reranking of retrieved chunks.
- Multi-hop or iterative retrieval loops.
- Retrieval from external APIs (the `allow_external=False` default is preserved).
- Evaluation harness or offline RAG quality metrics.
- Changes to the `search_documents` MCP tool or `RetrievalService`.
- Persistent session storage (dedup cache is in-memory and per-instance only).
- Cross-session chunk caching.
- Streaming answers.

## Further Notes

- The dedup cache is per-`RagAnsweringService` instance. If multiple instances are created per request (e.g. in tests), dedup will not kick in across instances. The intended deployment is one shared instance per agent process.
- `retrieval_confidence` thresholds (`"high"` ≥ 0.78, `"medium"` ≥ 0.62, `"low"` < 0.62) are defined in `retrieval/documents.py` and are not duplicated in the RAG layer — the RAG service reads the label, not the raw score.
- The `summary` stored in session refs should be extracted as the first sentence of the chunk (up to 120 chars) to stay lean while remaining human-readable in session inspection.
- Synthesis prompt template is internal to `RagAnsweringService` — it is not exposed as a public API. The prompt must instruct the model to cite using `[N]` markers matching source IDs, and must explicitly state that unsupported claims should not be made.
- Flash model name is resolved at construction time via `ModelRouter` to keep the service configuration-driven and consistent with all other agents in the system.
