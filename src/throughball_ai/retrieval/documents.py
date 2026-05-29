from typing import Protocol


MAX_TOP_K = 8
DEFAULT_TOP_K = 5
MAX_CHUNK_CHARS = 1000
EXPECTED_EMBEDDING_DIMENSION = 768


class EmbeddingDimensionError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    def embed_query(self, query: str) -> list[float]:
        ...


class VectorSearchRepository(Protocol):
    def match_document_chunks(
        self,
        *,
        query_embedding: list[float],
        match_count: int,
        city_id: str | None,
        team_id: str | None,
        category: str | None,
        query_text: str,
    ) -> list[dict]:
        ...


class RetrievalService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        repository: VectorSearchRepository,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._repository = repository
        self._max_chunk_chars = max_chunk_chars

    async def search(
        self,
        *,
        query: str,
        city_id: str | None,
        team_id: str | None,
        category: str | None,
        top_k: int,
        allow_external: bool,
    ) -> dict:
        bounded_top_k = min(max(top_k or DEFAULT_TOP_K, 1), MAX_TOP_K)
        try:
            query_embedding = self._embedding_provider.embed_query(query)
        except Exception:
            return _degraded_empty_result("embedding", "VECTOR_SEARCH_UNAVAILABLE")
        try:
            rows = self._repository.match_document_chunks(
                query_embedding=query_embedding,
                match_count=bounded_top_k,
                city_id=city_id,
                team_id=team_id,
                category=category,
                query_text=query,
            )
        except Exception:
            return _degraded_empty_result("rpc", "VECTOR_SEARCH_UNAVAILABLE")
        chunks = [_compact_chunk(str(row.get("chunk_text", "")), self._max_chunk_chars) for row in rows]
        source_paths = [row.get("source_path") for row in rows]
        similarity_scores = [float(row.get("similarity", 0.0)) for row in rows]
        document_titles = [row.get("title") for row in rows]

        return {
            "chunks": chunks,
            "source_paths": source_paths,
            "similarity_scores": similarity_scores,
            "document_titles": document_titles,
            "retrieval_confidence": _retrieval_confidence(similarity_scores),
            "degraded": False,
            "telemetry": {"external_search_used": False},
            "results": [
                {
                    "document_id": row.get("document_id"),
                    "document_type": row.get("category"),
                    "title": row.get("title"),
                    "snippet": chunk,
                    "source_type": row.get("source_type", "internal"),
                    "relevance_score": score,
                    "created_at": row.get("created_at"),
                }
                for row, chunk, score in zip(rows, chunks, similarity_scores)
            ],
        }


def validate_embedding_dimension(
    embedding_provider: EmbeddingProvider,
    expected_dimension: int = EXPECTED_EMBEDDING_DIMENSION,
) -> None:
    embedding = embedding_provider.embed_query("dimension validation")
    actual_dimension = len(embedding)
    if actual_dimension != expected_dimension:
        raise EmbeddingDimensionError(
            f"Embedding provider returned {actual_dimension} dimensions; expected {expected_dimension}."
        )


class PsycopgVectorSearchRepository:
    def __init__(self, database_url: str, connection_factory=None) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory or _connect

    def match_document_chunks(
        self,
        *,
        query_embedding: list[float],
        match_count: int,
        city_id: str | None,
        team_id: str | None,
        category: str | None,
        query_text: str,
    ) -> list[dict]:
        sql = """
            select *
            from match_document_chunks(
                %s::vector,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """
        params = (
            _format_vector(query_embedding),
            match_count,
            city_id,
            team_id,
            category,
            None,
            query_text,
        )
        with self._connection_factory(self._database_url) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def _retrieval_confidence(similarity_scores: list[float]) -> str:
    if not similarity_scores:
        return "none"
    top_score = max(similarity_scores)
    if top_score >= 0.78:
        return "high"
    if top_score >= 0.62:
        return "medium"
    return "low"


def _compact_chunk(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars].rstrip()
    sentence_end = max(candidate.rfind("."), candidate.rfind("!"), candidate.rfind("?"))
    if sentence_end >= max_chars // 3:
        return candidate[: sentence_end + 1]
    whitespace = candidate.rfind(" ")
    if whitespace >= max_chars // 2:
        return candidate[:whitespace].rstrip()
    return candidate


def _degraded_empty_result(failure_stage: str, degraded_reason: str) -> dict:
    return {
        "chunks": [],
        "source_paths": [],
        "similarity_scores": [],
        "document_titles": [],
        "retrieval_confidence": "none",
        "degraded": True,
        "telemetry": {
            "failure_stage": failure_stage,
            "degraded_reason": degraded_reason,
            "external_search_used": False,
        },
        "results": [],
    }


def _format_vector(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)
