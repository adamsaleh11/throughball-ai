import pytest

from throughball_ai.rag.prompt_builder import build_grounded_context
from throughball_ai.retrieval.documents import MAX_CHUNK_CHARS


def test_prompt_builder_renders_numbered_xml_source_blocks():
    context = build_grounded_context(
        chunks=["Chunk alpha text.", "Chunk beta text."],
        source_paths=["knowledge/doc-alpha.md", "knowledge/doc-beta.md"],
        titles=["Doc Alpha", "Doc Beta"],
        top_k=5,
    )

    assert '<source id="1" path="knowledge/doc-alpha.md">' in context
    assert "Chunk alpha text." in context
    assert '<source id="2" path="knowledge/doc-beta.md">' in context
    assert "Chunk beta text." in context
    assert "</source>" in context


def test_prompt_builder_ids_are_one_indexed_and_sequential():
    context = build_grounded_context(
        chunks=["A", "B", "C"],
        source_paths=["p/a.md", "p/b.md", "p/c.md"],
        titles=["A", "B", "C"],
        top_k=5,
    )

    assert 'id="1"' in context
    assert 'id="2"' in context
    assert 'id="3"' in context
    assert 'id="0"' not in context


def test_prompt_builder_returns_empty_string_for_empty_chunk_list():
    context = build_grounded_context(chunks=[], source_paths=[], titles=[], top_k=5)
    assert context == ""


def test_prompt_builder_total_output_does_not_exceed_cap():
    # Each chunk is MAX_CHUNK_CHARS long; top_k=3 so cap is 3*MAX_CHUNK_CHARS
    long_chunk = "x" * MAX_CHUNK_CHARS
    context = build_grounded_context(
        chunks=[long_chunk] * 5,
        source_paths=[f"p/{i}.md" for i in range(5)],
        titles=[f"Doc {i}" for i in range(5)],
        top_k=3,
    )

    assert len(context) <= 3 * MAX_CHUNK_CHARS + 200  # small allowance for XML tags


def test_prompt_builder_drops_whole_block_rather_than_truncating_mid_block():
    long_chunk = "y" * MAX_CHUNK_CHARS
    context = build_grounded_context(
        chunks=[long_chunk] * 5,
        source_paths=[f"p/{i}.md" for i in range(5)],
        titles=[f"Doc {i}" for i in range(5)],
        top_k=3,
    )
    # Should not contain id="4" or id="5" (those would push past cap)
    assert 'id="4"' not in context
    assert 'id="5"' not in context
    # The block that fits must be complete — no truncated </source>
    assert context.count("<source") == context.count("</source>")


def test_prompt_builder_single_chunk_at_max_chunk_chars_fits():
    chunk = "z" * MAX_CHUNK_CHARS
    context = build_grounded_context(
        chunks=[chunk],
        source_paths=["p/doc.md"],
        titles=["Doc"],
        top_k=5,
    )

    assert 'id="1"' in context
    assert chunk in context
