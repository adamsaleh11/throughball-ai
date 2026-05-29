from dataclasses import dataclass, field
from typing import Optional, Protocol

from throughball_ai.rag.citations import extract_citations
from throughball_ai.rag.grounding import GroundingEvaluator
from throughball_ai.rag.prompt_builder import build_grounded_context
from throughball_ai.rag.retriever import Retriever

_FALLBACK_ANSWER = (
    "I don't have enough reliable information to answer this confidently. "
    "Please consult official matchday sources."
)

_SYNTHESIS_PROMPT_TEMPLATE = """\
You are a helpful football fan assistant. Answer the question using ONLY the sources below.
Cite each piece of evidence with its source ID in square brackets, e.g. [1] or [2].
Do not make claims that are not supported by the provided sources.

{context}

Question: {question}

Answer:"""


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    confidence: str
    citations: list[dict]
    grounded: bool
    groundedness_reason: str
    chunk_ids_used: list[str]
    degraded: bool


class SynthesisAdapterProtocol(Protocol):
    async def synthesize(self, prompt: str) -> str: ...


class RetrievalServiceProtocol(Protocol):
    async def search(self, *, query: str, city_id, team_id, category, top_k: int, allow_external: bool) -> dict: ...


class SessionServiceProtocol(Protocol):
    def add_retrieval_reference(self, session_id: str, retrieval_ref: dict) -> None: ...


class RagAnsweringService:
    def __init__(
        self,
        *,
        retrieval_service: RetrievalServiceProtocol,
        session_service: SessionServiceProtocol,
        synthesis_adapter: SynthesisAdapterProtocol,
    ) -> None:
        self._retriever = Retriever(
            retrieval_service=retrieval_service,
            session_service=session_service,
        )
        self._synthesis_adapter = synthesis_adapter
        self._grounding_evaluator = GroundingEvaluator()

    async def answer(
        self,
        *,
        query: str,
        session_id: str,
        city_id: Optional[str] = None,
        team_id: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> RagAnswer:
        retrieval = await self._retriever.retrieve(
            query=query,
            session_id=session_id,
            city_id=city_id,
            team_id=team_id,
            category=category,
            top_k=top_k,
        )

        chunks = retrieval.get("chunks", [])
        source_paths = retrieval.get("source_paths", [])
        titles = retrieval.get("document_titles", [])
        confidence = retrieval.get("retrieval_confidence", "none")
        degraded = bool(retrieval.get("degraded", False))

        chunk_ids_used = [
            r.get("chunk_id", "") for r in retrieval.get("results", [])
        ]

        if not chunks:
            return _fallback(degraded=degraded)

        context = build_grounded_context(
            chunks=chunks,
            source_paths=source_paths,
            titles=titles,
            top_k=top_k,
        )
        prompt = _SYNTHESIS_PROMPT_TEMPLATE.format(context=context, question=query)
        raw_answer = await self._synthesis_adapter.synthesize(prompt)

        grounding = self._grounding_evaluator.evaluate(
            answer=raw_answer,
            retrieval_confidence=confidence,
            chunk_count=len(chunks),
        )

        if not grounding["grounded"]:
            return _fallback(degraded=degraded)

        citations = extract_citations(
            answer=raw_answer,
            source_paths=source_paths,
            titles=titles,
        )

        return RagAnswer(
            answer=raw_answer,
            confidence=confidence,
            citations=citations,
            grounded=True,
            groundedness_reason=grounding["groundedness_reason"],
            chunk_ids_used=chunk_ids_used,
            degraded=degraded,
        )


def _fallback(*, degraded: bool = False) -> RagAnswer:
    return RagAnswer(
        answer=_FALLBACK_ANSWER,
        confidence="none",
        citations=[],
        grounded=False,
        groundedness_reason="Insufficient evidence to ground the answer.",
        chunk_ids_used=[],
        degraded=degraded,
    )
