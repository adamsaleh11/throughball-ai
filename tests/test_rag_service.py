"""End-to-end tests for RagAnsweringService.

Covers all four ticket acceptance criteria:
  1. Answers cite retrieved evidence.
  2. Unsupported questions return a safe low-confidence answer.
  3. Context size is bounded.
  4. Retrieval reuse works within one session.
"""
import pytest

from throughball_ai.rag import RagAnswer, RagAnsweringService
from throughball_ai.retrieval.documents import MAX_CHUNK_CHARS


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeRetrievalService:
    def __init__(self, chunks=None, source_paths=None, titles=None, confidence="high", degraded=False):
        self.call_count = 0
        self._chunks = chunks or ["BMO Field is the main stadium. Fans gather here on matchdays."]
        self._source_paths = source_paths or ["knowledge/toronto-venues.md"]
        self._titles = titles or ["Toronto Venues"]
        self._confidence = confidence
        self._degraded = degraded

    async def search(self, *, query, city_id, team_id, category, top_k, allow_external):
        self.call_count += 1
        if self._degraded:
            return {
                "chunks": [], "source_paths": [], "similarity_scores": [],
                "document_titles": [], "retrieval_confidence": "none",
                "degraded": True,
                "telemetry": {"failure_stage": "embedding", "external_search_used": False},
                "results": [],
            }
        results = [
            {"chunk_id": f"chunk_{i}", "document_id": f"doc_{i}", "snippet": c,
             "source_type": "seeded", "relevance_score": 0.85}
            for i, c in enumerate(self._chunks, start=1)
        ]
        return {
            "chunks": self._chunks,
            "source_paths": self._source_paths,
            "similarity_scores": [0.85] * len(self._chunks),
            "document_titles": self._titles,
            "retrieval_confidence": self._confidence,
            "degraded": False,
            "telemetry": {"external_search_used": False},
            "results": results,
        }


class FakeSessionService:
    def __init__(self):
        self._refs: dict[str, list[dict]] = {}

    def add_retrieval_reference(self, session_id: str, retrieval_ref: dict) -> None:
        self._refs.setdefault(session_id, []).append(retrieval_ref)

    def refs_for(self, session_id: str) -> list[dict]:
        return self._refs.get(session_id, [])


class CitingSynthesisAdapter:
    """Always returns an answer that cites [1]."""

    async def synthesize(self, prompt: str) -> str:
        return "Fans gather at BMO Field on matchdays [1]."


class NonCitingSynthesisAdapter:
    """Returns an answer with no citation markers."""

    async def synthesize(self, prompt: str) -> str:
        return "Fans gather somewhere in the city."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(retrieval_service=None, session_service=None, synthesis_adapter=None):
    return RagAnsweringService(
        retrieval_service=retrieval_service or FakeRetrievalService(),
        session_service=session_service or FakeSessionService(),
        synthesis_adapter=synthesis_adapter or CitingSynthesisAdapter(),
    )


# ---------------------------------------------------------------------------
# Acceptance criterion 1: Answers cite retrieved evidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_service_answer_contains_citation_on_happy_path():
    service = _make_service()

    answer = await service.answer(
        query="Where do fans gather?",
        session_id="sess_1",
        city_id="city_toronto",
    )

    assert isinstance(answer, RagAnswer)
    assert answer.grounded is True
    assert len(answer.citations) >= 1
    assert answer.citations[0]["source_path"] == "knowledge/toronto-venues.md"
    assert "[1]" in answer.answer


@pytest.mark.asyncio
async def test_rag_service_returns_rag_answer_dataclass_with_all_fields():
    service = _make_service()

    answer = await service.answer(query="fan info", session_id="sess_1")

    assert hasattr(answer, "answer")
    assert hasattr(answer, "confidence")
    assert hasattr(answer, "citations")
    assert hasattr(answer, "grounded")
    assert hasattr(answer, "groundedness_reason")
    assert hasattr(answer, "chunk_ids_used")
    assert hasattr(answer, "degraded")


# ---------------------------------------------------------------------------
# Acceptance criterion 2: Unsupported questions return safe low-confidence answer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_service_returns_safe_fallback_when_no_chunks_retrieved():
    retrieval = FakeRetrievalService(degraded=True)
    service = _make_service(retrieval_service=retrieval)

    answer = await service.answer(query="unknown topic", session_id="sess_1")

    assert answer.grounded is False
    assert answer.confidence == "none"
    assert answer.citations == []
    assert "reliable information" in answer.answer.lower() or "official" in answer.answer.lower()
    assert answer.degraded is True


@pytest.mark.asyncio
async def test_rag_service_returns_safe_fallback_when_synthesis_produces_no_citation():
    service = _make_service(synthesis_adapter=NonCitingSynthesisAdapter())

    answer = await service.answer(query="fan gathering", session_id="sess_1")

    assert answer.grounded is False
    assert answer.confidence == "none"
    assert answer.citations == []


# ---------------------------------------------------------------------------
# Acceptance criterion 3: Context size is bounded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_service_bounds_context_fed_to_synthesis():
    long_chunks = ["x" * MAX_CHUNK_CHARS] * 10
    long_paths = [f"knowledge/doc-{i}.md" for i in range(10)]
    long_titles = [f"Doc {i}" for i in range(10)]
    retrieval = FakeRetrievalService(chunks=long_chunks, source_paths=long_paths, titles=long_titles)

    captured_prompts: list[str] = []

    class CapturingAdapter:
        async def synthesize(self, prompt: str) -> str:
            captured_prompts.append(prompt)
            return "Fans gather here [1]."

    service = _make_service(retrieval_service=retrieval, synthesis_adapter=CapturingAdapter())
    await service.answer(query="venues", session_id="sess_1", top_k=5)

    assert captured_prompts, "Synthesis adapter was never called"
    # Context in the prompt must not exceed top_k * MAX_CHUNK_CHARS + generous tag overhead
    assert len(captured_prompts[0]) <= 5 * MAX_CHUNK_CHARS + 2000


# ---------------------------------------------------------------------------
# Acceptance criterion 4: Retrieval reuse works within one session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_service_reuses_retrieval_within_same_session():
    retrieval = FakeRetrievalService()
    service = _make_service(retrieval_service=retrieval)

    await service.answer(query="fan gathering", session_id="sess_1")
    await service.answer(query="fan gathering", session_id="sess_1")

    assert retrieval.call_count == 1


@pytest.mark.asyncio
async def test_rag_service_does_not_reuse_retrieval_across_sessions():
    retrieval = FakeRetrievalService()
    service = _make_service(retrieval_service=retrieval)

    await service.answer(query="fan gathering", session_id="sess_1")
    await service.answer(query="fan gathering", session_id="sess_2")

    assert retrieval.call_count == 2


# ---------------------------------------------------------------------------
# Ancillary: chunk_ids_used and degraded flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_service_populates_chunk_ids_used():
    service = _make_service()

    answer = await service.answer(query="venues", session_id="sess_1")

    assert len(answer.chunk_ids_used) >= 1


@pytest.mark.asyncio
async def test_rag_service_sets_degraded_true_when_retrieval_is_degraded():
    service = _make_service(retrieval_service=FakeRetrievalService(degraded=True))

    answer = await service.answer(query="venues", session_id="sess_1")

    assert answer.degraded is True
