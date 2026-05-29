import pytest

from throughball_ai.rag.citations import extract_citations
from throughball_ai.rag.grounding import GroundingEvaluator


# ---------------------------------------------------------------------------
# GroundingEvaluator
# ---------------------------------------------------------------------------

def test_grounding_is_false_when_retrieval_confidence_is_none():
    evaluator = GroundingEvaluator()
    result = evaluator.evaluate(
        answer="The stadium is large.",
        retrieval_confidence="none",
        chunk_count=0,
    )
    assert result["grounded"] is False
    assert "confidence" in result["groundedness_reason"].lower() or "none" in result["groundedness_reason"].lower()


def test_grounding_is_false_when_answer_contains_no_citation_marker():
    evaluator = GroundingEvaluator()
    result = evaluator.evaluate(
        answer="The stadium is large.",
        retrieval_confidence="high",
        chunk_count=2,
    )
    assert result["grounded"] is False
    assert "citation" in result["groundedness_reason"].lower() or "cite" in result["groundedness_reason"].lower()


def test_grounding_is_true_when_answer_cites_a_valid_chunk():
    evaluator = GroundingEvaluator()
    result = evaluator.evaluate(
        answer="The stadium holds 30,000 fans [1].",
        retrieval_confidence="high",
        chunk_count=2,
    )
    assert result["grounded"] is True


def test_grounding_is_true_for_low_confidence_when_citation_present():
    evaluator = GroundingEvaluator()
    result = evaluator.evaluate(
        answer="Some fans gather at Pub Row [1].",
        retrieval_confidence="low",
        chunk_count=1,
    )
    assert result["grounded"] is True


def test_grounding_is_false_when_citation_marker_is_out_of_range():
    evaluator = GroundingEvaluator()
    result = evaluator.evaluate(
        answer="Based on evidence [99], the answer is clear.",
        retrieval_confidence="high",
        chunk_count=2,
    )
    assert result["grounded"] is False


# ---------------------------------------------------------------------------
# extract_citations
# ---------------------------------------------------------------------------

def test_extract_citations_maps_markers_to_source_paths_and_titles():
    citations = extract_citations(
        answer="Fans gather here [1] and also there [2].",
        source_paths=["knowledge/doc-a.md", "knowledge/doc-b.md"],
        titles=["Doc A", "Doc B"],
    )
    assert len(citations) == 2
    assert citations[0] == {"id": 1, "source_path": "knowledge/doc-a.md", "title": "Doc A"}
    assert citations[1] == {"id": 2, "source_path": "knowledge/doc-b.md", "title": "Doc B"}


def test_extract_citations_silently_drops_out_of_range_markers():
    citations = extract_citations(
        answer="Evidence [0] and [99] are cited.",
        source_paths=["knowledge/doc-a.md"],
        titles=["Doc A"],
    )
    assert citations == []


def test_extract_citations_deduplicates_repeated_markers():
    citations = extract_citations(
        answer="See [1] and also [1] again.",
        source_paths=["knowledge/doc-a.md"],
        titles=["Doc A"],
    )
    assert len(citations) == 1
    assert citations[0]["id"] == 1


def test_extract_citations_returns_empty_list_for_empty_answer():
    citations = extract_citations(answer="", source_paths=["knowledge/doc.md"], titles=["Doc"])
    assert citations == []


def test_extract_citations_returns_empty_list_when_no_markers_present():
    citations = extract_citations(
        answer="No citations here at all.",
        source_paths=["knowledge/doc.md"],
        titles=["Doc"],
    )
    assert citations == []
