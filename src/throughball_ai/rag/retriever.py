from typing import Any, Optional, Protocol

from throughball_ai.retrieval.documents import MAX_TOP_K


class RetrievalServiceProtocol(Protocol):
    async def search(
        self,
        *,
        query: str,
        city_id: str | None,
        team_id: str | None,
        category: str | None,
        top_k: int,
        allow_external: bool,
    ) -> dict: ...


class SessionServiceProtocol(Protocol):
    def add_retrieval_reference(self, session_id: str, retrieval_ref: dict) -> None: ...


class Retriever:
    def __init__(
        self,
        *,
        retrieval_service: RetrievalServiceProtocol,
        session_service: SessionServiceProtocol,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._session_service = session_service
        self._query_cache: dict[tuple[str, str], dict] = {}

    async def retrieve(
        self,
        *,
        query: str,
        session_id: str,
        city_id: Optional[str] = None,
        team_id: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> dict:
        cache_key = (session_id, _normalize(query))
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        bounded_top_k = min(max(top_k, 1), MAX_TOP_K)
        result = await self._retrieval_service.search(
            query=query,
            city_id=city_id,
            team_id=team_id,
            category=category,
            top_k=bounded_top_k,
            allow_external=False,
        )

        self._query_cache[cache_key] = result

        if not result.get("degraded"):
            chunks = result.get("chunks", [])
            source_paths = result.get("source_paths", [])
            raw_results = result.get("results", [])
            for i, (chunk, source_path) in enumerate(zip(chunks, source_paths)):
                chunk_id = raw_results[i].get("chunk_id") if i < len(raw_results) else None
                self._session_service.add_retrieval_reference(
                    session_id,
                    {
                        "chunk_id": chunk_id,
                        "source_path": source_path,
                        "summary": _first_sentence(chunk),
                    },
                )

        return result


def _normalize(query: str) -> str:
    return query.strip().lower()


def _first_sentence(text: str, max_chars: int = 120) -> str:
    end = max(text.find("."), text.find("!"), text.find("?"))
    if 0 < end < max_chars:
        return text[: end + 1]
    return text[:max_chars].rstrip()
