import os
from typing import Optional

from throughball_ai.ingestion.embeddings import VertexTextEmbeddingClient
from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import SearchDocumentsInput, SearchDocumentsOutput
from throughball_ai.retrieval.documents import (
    PsycopgVectorSearchRepository,
    RetrievalService,
    validate_embedding_dimension,
)

TOOL_NAME = "search_documents"
TIMEOUT_MS = 1800
_retrieval_service = None


def set_retrieval_service(service) -> None:
    global _retrieval_service
    _retrieval_service = service


class VertexQueryEmbeddingProvider:
    def __init__(self, client: VertexTextEmbeddingClient):
        self._client = client

    def embed_query(self, query: str) -> list[float]:
        return self._client.embed([query])[0]


def build_default_retrieval_service() -> RetrievalService:
    embedding_provider = VertexQueryEmbeddingProvider(
        VertexTextEmbeddingClient(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
            model_name=os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-004"),
            task_type="RETRIEVAL_QUERY",
        )
    )
    validate_embedding_dimension(embedding_provider)
    return RetrievalService(
        embedding_provider=embedding_provider,
        repository=PsycopgVectorSearchRepository(os.environ["SUPABASE_DB_URL"]),
    )


async def handler(
    query: Optional[str] = None,
    city_id: Optional[str] = None,
    team_id: Optional[str] = None,
    category: Optional[str] = None,
    top_k: int = 5,
    filters: Optional[dict] = None,
    limit: Optional[int] = None,
    include_snippets: bool = True,
    allow_external: bool = False,
) -> dict:
    if not query:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="query is required.",
            details={"field": "query"},
        )

    normalized_city_id = city_id or (filters or {}).get("city_id")
    normalized_team_id = team_id or (filters or {}).get("team_id")
    normalized_category = category or (filters or {}).get("category") or (filters or {}).get("document_type")
    normalized_top_k = limit if limit is not None else top_k

    if not _retrieval_configured():
        return _degraded_empty_result("config", "SEARCH_UNAVAILABLE")

    service = _retrieval_service
    if service is None:
        try:
            service = build_default_retrieval_service()
            set_retrieval_service(service)
        except Exception:
            return _degraded_empty_result("config", "SEARCH_UNAVAILABLE")

    data = await service.search(
        query=query,
        city_id=normalized_city_id,
        team_id=normalized_team_id,
        category=normalized_category,
        top_k=normalized_top_k,
        allow_external=allow_external,
    )
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "none" if data.get("degraded") else "internal",
        "data": data,
        "telemetry": {
            "degraded": bool(data.get("degraded")),
            "degraded_reason": data.get("telemetry", {}).get("degraded_reason"),
            "source_type": "none" if data.get("degraded") else "internal",
            "external_api_called": False,
        },
    }


def _retrieval_configured() -> bool:
    return bool(
        os.getenv("SUPABASE_DB_URL")
        and os.getenv("GOOGLE_CLOUD_PROJECT")
        and os.getenv("GOOGLE_CLOUD_LOCATION")
    )


def _degraded_empty_result(failure_stage: str, reason: str) -> dict:
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "none",
        "data": {
            "chunks": [],
            "source_paths": [],
            "similarity_scores": [],
            "document_titles": [],
            "retrieval_confidence": "none",
            "degraded": True,
            "telemetry": {
                "failure_stage": failure_stage,
                "external_search_used": False,
            },
            "results": [],
        },
        "telemetry": {
            "degraded": True,
            "degraded_reason": reason,
            "source_type": "none",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=SearchDocumentsInput,
    output_schema=SearchDocumentsOutput,
    cacheable=True,
    max_retry_count=1,
    description="Searches retrieved evidence documents for agent synthesis.",
)
