import pytest

from throughball_ai.retrieval.documents import (
    EmbeddingDimensionError,
    PsycopgVectorSearchRepository,
    RetrievalService,
    validate_embedding_dimension,
)


class FakeEmbeddingProvider:
    def __init__(self):
        self.queries = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.1, 0.2, 0.3]


class FakeVectorSearchRepository:
    def __init__(self):
        self.calls = []

    def match_document_chunks(
        self,
        *,
        query_embedding,
        match_count,
        city_id,
        team_id,
        category,
        query_text,
    ) -> list[dict]:
        self.calls.append(
            {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "city_id": city_id,
                "team_id": team_id,
                "category": category,
                "query_text": query_text,
            }
        )
        return [
            {
                "chunk_id": "chunk_1",
                "document_id": "doc_1",
                "chunk_text": "BMO Field has supporter pubs nearby for matchday gatherings.",
                "title": "Toronto Stadium Guide",
                "category": "venues",
                "source_type": "seeded",
                "source_path": "knowledge/seed-documents/venues/toronto-stadium-guide.md",
                "similarity": 0.83,
            }
        ]


class FailingEmbeddingProvider:
    def embed_query(self, query: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


class FailingVectorSearchRepository:
    def match_document_chunks(self, **_kwargs) -> list[dict]:
        raise RuntimeError("rpc unavailable")


class ScoredVectorSearchRepository:
    def __init__(self, scores):
        self.scores = scores

    def match_document_chunks(self, **_kwargs) -> list[dict]:
        return [
            {
                "chunk_id": f"chunk_{index}",
                "document_id": f"doc_{index}",
                "chunk_text": f"Evidence {index}",
                "title": f"Document {index}",
                "category": "venues",
                "source_type": "seeded",
                "source_path": f"knowledge/doc-{index}.md",
                "similarity": score,
            }
            for index, score in enumerate(self.scores, start=1)
        ]


@pytest.mark.asyncio
async def test_retrieval_service_embeds_query_and_passes_exact_filters_to_vector_search():
    embedder = FakeEmbeddingProvider()
    repository = FakeVectorSearchRepository()
    service = RetrievalService(embedding_provider=embedder, repository=repository)

    result = await service.search(
        query="supporter pubs near BMO Field",
        city_id="city_toronto",
        team_id="team_canada",
        category="venues",
        top_k=3,
        allow_external=True,
    )

    assert embedder.queries == ["supporter pubs near BMO Field"]
    assert repository.calls == [
        {
            "query_embedding": [0.1, 0.2, 0.3],
            "match_count": 3,
            "city_id": "city_toronto",
            "team_id": "team_canada",
            "category": "venues",
            "query_text": "supporter pubs near BMO Field",
        }
    ]
    assert result["chunks"] == ["BMO Field has supporter pubs nearby for matchday gatherings."]
    assert result["source_paths"] == ["knowledge/seed-documents/venues/toronto-stadium-guide.md"]
    assert result["similarity_scores"] == [0.83]
    assert result["document_titles"] == ["Toronto Stadium Guide"]
    assert result["retrieval_confidence"] == "high"
    assert result["degraded"] is False
    assert result["telemetry"]["external_search_used"] is False


@pytest.mark.asyncio
async def test_retrieval_service_returns_degraded_empty_result_when_embedding_fails():
    service = RetrievalService(
        embedding_provider=FailingEmbeddingProvider(),
        repository=FakeVectorSearchRepository(),
    )

    result = await service.search(
        query="supporter pubs",
        city_id=None,
        team_id=None,
        category=None,
        top_k=5,
        allow_external=False,
    )

    assert result["chunks"] == []
    assert result["source_paths"] == []
    assert result["similarity_scores"] == []
    assert result["document_titles"] == []
    assert result["retrieval_confidence"] == "none"
    assert result["degraded"] is True
    assert result["telemetry"]["failure_stage"] == "embedding"
    assert result["telemetry"]["external_search_used"] is False
    assert result["results"] == []


@pytest.mark.asyncio
async def test_retrieval_service_returns_degraded_empty_result_when_vector_search_fails():
    service = RetrievalService(
        embedding_provider=FakeEmbeddingProvider(),
        repository=FailingVectorSearchRepository(),
    )

    result = await service.search(
        query="supporter pubs",
        city_id=None,
        team_id=None,
        category=None,
        top_k=5,
        allow_external=False,
    )

    assert result["chunks"] == []
    assert result["retrieval_confidence"] == "none"
    assert result["degraded"] is True
    assert result["telemetry"]["failure_stage"] == "rpc"
    assert result["telemetry"]["external_search_used"] is False
    assert result["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scores", "expected_confidence"),
    [
        ([0.78], "high"),
        ([0.62], "medium"),
        ([0.4], "low"),
        ([], "none"),
    ],
)
async def test_retrieval_confidence_uses_higher_is_better_cosine_similarity(scores, expected_confidence):
    service = RetrievalService(
        embedding_provider=FakeEmbeddingProvider(),
        repository=ScoredVectorSearchRepository(scores),
    )

    result = await service.search(
        query="supporter pubs",
        city_id=None,
        team_id=None,
        category=None,
        top_k=5,
        allow_external=False,
    )

    assert result["retrieval_confidence"] == expected_confidence
    assert result["degraded"] is False


@pytest.mark.asyncio
async def test_retrieval_service_compacts_long_chunks_at_sentence_boundary_when_possible():
    class LongChunkRepository:
        def match_document_chunks(self, **_kwargs) -> list[dict]:
            return [
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "chunk_text": "Useful first sentence. " + "extra " * 40,
                    "title": "Doc",
                    "category": "venues",
                    "source_type": "seeded",
                    "source_path": "knowledge/doc.md",
                    "similarity": 0.8,
                }
            ]

    service = RetrievalService(
        embedding_provider=FakeEmbeddingProvider(),
        repository=LongChunkRepository(),
        max_chunk_chars=50,
    )

    result = await service.search(
        query="supporter pubs",
        city_id=None,
        team_id=None,
        category=None,
        top_k=5,
        allow_external=False,
    )

    assert result["chunks"] == ["Useful first sentence."]


def test_vector_search_repository_calls_match_document_chunks_rpc_with_exact_parameters():
    class FakeCursor:
        def __init__(self):
            self.sql = None
            self.params = None

        def execute(self, sql, params):
            self.sql = sql
            self.params = params
            return self

        def fetchall(self):
            return [
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "chunk_text": "Evidence",
                    "chunk_index": 0,
                    "title": "Title",
                    "category": "venues",
                    "city_id": "city_toronto",
                    "team_id": "team_canada",
                    "source_type": "seeded",
                    "source_path": "knowledge/doc.md",
                    "similarity": 0.7,
                }
            ]

    class FakeConnection:
        def __init__(self, cursor):
            self.cursor = cursor

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            return self.cursor.execute(sql, params)

    cursor = FakeCursor()
    repository = PsycopgVectorSearchRepository(
        database_url="postgres://example",
        connection_factory=lambda _database_url: FakeConnection(cursor),
    )

    rows = repository.match_document_chunks(
        query_embedding=[0.1, 0.2, 0.3],
        match_count=3,
        city_id="city_toronto",
        team_id="team_canada",
        category="venues",
        query_text="supporter pubs",
    )

    assert "match_document_chunks" in cursor.sql
    assert cursor.params == (
        "[0.1,0.2,0.3]",
        3,
        "city_toronto",
        "team_canada",
        "venues",
        None,
        "supporter pubs",
    )
    assert rows[0]["source_path"] == "knowledge/doc.md"


def test_embedding_dimension_validation_fails_fast_for_incompatible_provider():
    class WrongDimensionEmbeddingProvider:
        def embed_query(self, query: str) -> list[float]:
            return [0.1, 0.2]

    with pytest.raises(EmbeddingDimensionError, match="768"):
        validate_embedding_dimension(WrongDimensionEmbeddingProvider(), expected_dimension=768)
