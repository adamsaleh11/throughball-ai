# Plan: RAG Answering Service

> Source PRD: docs/prds/09-01-rag-answering-service.md

## Architectural decisions

- **Module layout**: `src/throughball_ai/rag/` — `retriever.py`, `prompt_builder.py`, `grounding.py`, `citations.py`, `service.py` (orchestrator), `__init__.py` (re-exports)
- **Retrieval boundary**: `Retriever` calls `RetrievalService` directly (no MCP layer). `RetrievalService` is injected at construction, not constructed internally.
- **Session dedup key**: `(session_id, normalized_query)` where normalization is lowercase + strip. Per-`RagAnsweringService` instance cache — no cross-session pollution.
- **Session state writes**: `chunk_id`, `source_path`, first-sentence summary ≤ 120 chars written via `InMemorySessionService.add_retrieval_reference()`. Full chunk text is never stored.
- **Context cap**: `top_k × MAX_CHUNK_CHARS` total chars (default 5 × 1000 = 5,000). Excess chunks dropped, not truncated mid-block.
- **Grounding mechanism**: Heuristic only. Two conditions: `retrieval_confidence == "none"` → ungrounded; no `[N]` citation present in answer → ungrounded.
- **Citation format**: Inline `[N]` markers in answer text + separate `citations: list[dict]` with `id`, `source_path`, `title`.
- **Return type**: Typed `RagAnswer` dataclass — `answer`, `confidence`, `citations`, `grounded`, `groundedness_reason`, `chunk_ids_used`, `degraded`.
- **Low-confidence fallback**: Fixed string `"I don't have enough reliable information to answer this confidently. Please consult official matchday sources."` — never speculative.
- **Synthesis model**: Gemini Flash only, resolved via `ModelRouter`. Flash-only guard asserted at construction time.
- **Synthesis adapter**: Injectable (mirrors `GeminiFlashSynthesisAdapter` in `fan_gathering.py`) so tests never hit live inference.
- **`top_k` bounds**: Default 5, max 8 (existing `MAX_TOP_K` constant from `retrieval/documents.py`).
- **Testing pattern**: `@pytest.mark.asyncio`, injected fakes at `RetrievalService` boundary (mirrors `FakeEmbeddingProvider` / `FakeVectorSearchRepository` in `test_document_retrieval.py`). No `unittest.mock.patch` on globals.

---

## Phase 1: Core Retriever with Session Dedup

**User stories**: 2, 3, 10, 12, 15

### What to build

Build `Retriever` in `retriever.py`. It wraps an injected `RetrievalService` and an injected `InMemorySessionService`. It maintains a per-instance `_query_cache` keyed by `(session_id, normalized_query)` — normalized means lowercase and stripped.

On a cache hit, return the cached chunks immediately without re-embedding or re-querying. On a cache miss, call `RetrievalService.search()`, populate the cache, and write compact retrieval refs to the session via `add_retrieval_reference()`. Each ref contains `chunk_id`, `source_path`, and a short summary (first sentence of the chunk, capped at 120 chars). Clamp `top_k` to the existing `MAX_TOP_K` constant. Propagate degraded results cleanly — a degraded search returns empty chunks and sets `degraded=True` in the returned structure.

All behavior is testable with `FakeRetrievalService` and a real `InMemorySessionService` — no live DB or Vertex.

### Acceptance criteria

- [ ] Cache hit for the same `(session_id, normalized_query)` returns cached chunks without calling `RetrievalService` a second time
- [ ] Cache miss calls `RetrievalService.search()` and populates the cache
- [ ] After a cache miss, `InMemorySessionService.retrieval_refs` contains one ref per retrieved chunk with `chunk_id`, `source_path`, and a `summary` ≤ 120 chars
- [ ] `top_k` is clamped to `MAX_TOP_K` (8) regardless of caller input
- [ ] Query normalization treats `"  Fan Hotspots  "` and `"fan hotspots"` as the same cache key
- [ ] Degraded `RetrievalService` response produces empty chunks and `degraded=True`
- [ ] Second call with the same session + query does NOT append additional refs to the session
- [ ] Different session IDs maintain independent caches

---

## Phase 2: Grounded Context Assembly

**User stories**: 7, 9

### What to build

Build `build_grounded_context()` as a pure function in `prompt_builder.py`. It accepts a list of chunk texts, source paths, and titles, and returns a single formatted string for injection into a synthesis prompt.

Each chunk is rendered as a numbered XML-style source block:
```
<source id="1" path="knowledge/...">
chunk text
</source>
```

Apply a hard character cap: total output is at most `top_k × MAX_CHUNK_CHARS` characters. If adding the next block would exceed the cap, drop it entirely — never truncate mid-block. Return an empty string when no chunks are provided.

### Acceptance criteria

- [ ] Output contains one `<source id="N" ...>` block per chunk
- [ ] `id` values are 1-indexed and sequential
- [ ] `path` attribute matches the corresponding `source_path`
- [ ] Total output length never exceeds `top_k × MAX_CHUNK_CHARS`
- [ ] When the cap is reached, the last included block is complete — no partial blocks
- [ ] Empty chunk list returns an empty string
- [ ] Single chunk with text at exactly `MAX_CHUNK_CHARS` fits within the cap

---

## Phase 3: Groundedness Evaluation and Citation Extraction

**User stories**: 6, 13, 14

### What to build

Build `GroundingEvaluator` in `grounding.py`. It evaluates two heuristic conditions against the answer string and retrieval metadata — no LLM calls:

1. If `retrieval_confidence == "none"`, the answer is ungrounded regardless of content.
2. If the answer contains no `[N]` citation marker where N is a valid 1-based index into the retrieved chunks, the answer is ungrounded.

It returns `grounded: bool` and `groundedness_reason: str`.

Build `extract_citations()` as a pure function in `citations.py`. It regex-scans the answer for `[N]` markers, maps each N to the corresponding entry in `source_paths` and `titles` (1-indexed), and returns `[{"id": N, "source_path": "...", "title": "..."}]`. Markers referencing out-of-range indices are silently dropped. Duplicate `[N]` markers produce one citation entry. Empty answer returns an empty list.

### Acceptance criteria

- [ ] `retrieval_confidence == "none"` → `grounded=False` regardless of answer content
- [ ] Answer with no `[N]` marker → `grounded=False` with reason explaining missing citation
- [ ] Answer containing `[1]` where chunk 1 exists → `grounded=True`
- [ ] `retrieval_confidence == "low"` with a valid citation → `grounded=True` (confidence is not itself a disqualifier)
- [ ] `extract_citations` maps `[1]` and `[2]` to the correct source paths and titles
- [ ] `[0]` and `[99]` (out-of-range) are silently dropped
- [ ] Duplicate `[1][1]` in the answer produces exactly one citation entry
- [ ] Empty answer returns `[]` from `extract_citations`

---

## Phase 4: Orchestrated RagAnsweringService with Typed Return

**User stories**: 1, 4, 5, 8, 11

### What to build

Wire all modules into `RagAnsweringService` in `service.py`. Expose a single async method `answer(query, session_id, *, city_id, team_id, category, top_k) -> RagAnswer`.

The orchestration sequence is: `Retriever.retrieve()` → `build_grounded_context()` → Flash synthesis (via injectable adapter) → `GroundingEvaluator.evaluate()` → `extract_citations()` → return `RagAnswer`.

The synthesis adapter is injected at construction (defaults to the live `GeminiFlashSynthesisAdapter`). The synthesis prompt instructs the model to use `[N]` citation markers and not make unsupported claims. A Flash-only guard asserts at construction time that the resolved model name does not contain `"pro"`.

The low-confidence fallback is triggered when `GroundingEvaluator` returns `grounded=False` or when retrieval returns no chunks. The fallback returns the fixed safe string with `confidence="none"`, `grounded=False`, and `citations=[]`.

`RagAnswer` is a frozen dataclass exported from `rag/__init__.py` alongside `RagAnsweringService`.

End-to-end tests use a `FakeRetrievalService` returning canned chunks and a `FakeSynthesisAdapter` returning a canned answer string — no live inference or DB.

### Acceptance criteria

- [ ] `answer()` returns a `RagAnswer` dataclass on the happy path with `grounded=True` and `len(citations) >= 1`
- [ ] Low-confidence fallback fires when no chunks are retrieved; answer is the fixed safe string
- [ ] Low-confidence fallback fires when synthesis adapter returns an answer with no `[N]` citation; answer is the fixed safe string
- [ ] Session dedup: calling `answer()` twice with the same query in the same session triggers `RetrievalService` only once
- [ ] `chunk_ids_used` in `RagAnswer` lists the IDs of the retrieved chunks
- [ ] Flash-only guard raises at construction time when `ModelRouter` returns a Pro model
- [ ] `RagAnswer` and `RagAnsweringService` are importable from `throughball_ai.rag`
- [ ] `degraded=True` in `RagAnswer` when retrieval was degraded
- [ ] All four ticket acceptance criteria pass: answers cite evidence, unsupported questions return safe low-confidence answer, context size is bounded, retrieval reuse works within one session
