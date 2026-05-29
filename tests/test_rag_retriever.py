import pytest

from throughball_ai.rag.retriever import Retriever


class FakeSessionService:
    """Minimal stand-in for InMemorySessionService — avoids circular adk import."""

    def __init__(self):
        self._refs: dict[str, list[dict]] = {}

    def add_retrieval_reference(self, session_id: str, retrieval_ref: dict) -> None:
        self._refs.setdefault(session_id, []).append(retrieval_ref)

    def refs_for(self, session_id: str) -> list[dict]:
        return self._refs.get(session_id, [])


class FakeRetrievalService:
    def __init__(self, chunks=None, source_paths=None, titles=None, similarity_scores=None, confidence="high", degraded=False):
        self.calls = []
        self._chunks = chunks or ["Chunk A text.", "Chunk B text."]
        self._source_paths = source_paths or ["knowledge/doc-a.md", "knowledge/doc-b.md"]
        self._titles = titles or ["Doc A", "Doc B"]
        self._scores = similarity_scores or [0.85, 0.80]
        self._confidence = confidence
        self._degraded = degraded

    async def search(self, *, query, city_id, team_id, category, top_k, allow_external):
        self.calls.append(dict(query=query, city_id=city_id, top_k=top_k))
        if self._degraded:
            return {
                "chunks": [],
                "source_paths": [],
                "similarity_scores": [],
                "document_titles": [],
                "retrieval_confidence": "none",
                "degraded": True,
                "telemetry": {"failure_stage": "embedding", "external_search_used": False},
                "results": [],
            }
        results = [
            {
                "document_id": f"doc_{i}",
                "chunk_id": f"chunk_{i}",
                "snippet": chunk,
                "source_type": "seeded",
                "relevance_score": score,
            }
            for i, (chunk, score) in enumerate(zip(self._chunks, self._scores), start=1)
        ]
        return {
            "chunks": self._chunks,
            "source_paths": self._source_paths,
            "similarity_scores": self._scores,
            "document_titles": self._titles,
            "retrieval_confidence": self._confidence,
            "degraded": False,
            "telemetry": {"external_search_used": False},
            "results": results,
        }


@pytest.mark.asyncio
async def test_retriever_returns_chunks_from_retrieval_service():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    result = await retriever.retrieve(
        query="Where do fans gather?",
        session_id="sess_1",
        city_id="city_toronto",
        team_id=None,
        category=None,
        top_k=5,
    )

    assert result["chunks"] == ["Chunk A text.", "Chunk B text."]
    assert result["source_paths"] == ["knowledge/doc-a.md", "knowledge/doc-b.md"]
    assert result["retrieval_confidence"] == "high"
    assert result["degraded"] is False


@pytest.mark.asyncio
async def test_retriever_cache_hit_skips_retrieval_service_on_second_call():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="fan pubs near stadium", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)
    await retriever.retrieve(query="fan pubs near stadium", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)

    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_retriever_cache_normalises_query_case_and_whitespace():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="  Fan Hotspots  ", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)
    await retriever.retrieve(query="fan hotspots", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)

    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_retriever_different_sessions_do_not_share_cache():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="fan pubs", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)
    await retriever.retrieve(query="fan pubs", session_id="sess_2", city_id=None, team_id=None, category=None, top_k=5)

    assert len(service.calls) == 2


@pytest.mark.asyncio
async def test_retriever_writes_compact_refs_to_session_after_retrieval():
    service = FakeRetrievalService(
        chunks=["BMO Field is the main stadium. Extra words follow."],
        source_paths=["knowledge/toronto-venues.md"],
        titles=["Toronto Venues"],
        similarity_scores=[0.88],
        confidence="high",
    )
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="stadium info", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)

    refs = session_service.refs_for("sess_1")
    assert len(refs) == 1
    assert refs[0]["source_path"] == "knowledge/toronto-venues.md"
    assert "summary" in refs[0]
    assert len(refs[0]["summary"]) <= 120


@pytest.mark.asyncio
async def test_retriever_does_not_duplicate_refs_on_cache_hit():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="fan pubs", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)
    refs_after_first = len(session_service.refs_for("sess_1"))

    await retriever.retrieve(query="fan pubs", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)
    refs_after_second = len(session_service.refs_for("sess_1"))

    assert refs_after_first == refs_after_second


@pytest.mark.asyncio
async def test_retriever_clamps_top_k_to_maximum():
    service = FakeRetrievalService()
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    await retriever.retrieve(query="venues", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=99)

    assert service.calls[0]["top_k"] == 8


@pytest.mark.asyncio
async def test_retriever_propagates_degraded_retrieval_result():
    service = FakeRetrievalService(degraded=True)
    session_service = FakeSessionService()
    retriever = Retriever(retrieval_service=service, session_service=session_service)

    result = await retriever.retrieve(query="venues", session_id="sess_1", city_id=None, team_id=None, category=None, top_k=5)

    assert result["degraded"] is True
    assert result["chunks"] == []
