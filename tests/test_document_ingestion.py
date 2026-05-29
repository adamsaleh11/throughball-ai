from pathlib import Path

import pytest

from throughball_ai.ingestion.embeddings import estimate_embedding_cost
from throughball_ai.ingestion.chunking import chunk_markdown, content_hash
from throughball_ai.ingestion.ingest_documents import (
    IngestionConfigurationError,
    IngestionPipeline,
    IngestionSettings,
    PostgresDocumentStore,
)


class FakeStore:
    def __init__(self, existing_hashes=None):
        self.existing_hashes = set(existing_hashes or [])
        self.upserted_documents = []
        self.stored_chunks = []

    def existing_content_hashes(self, content_hashes, embedding_model):
        return self.existing_hashes.intersection(content_hashes)

    def upsert_documents(self, documents):
        self.upserted_documents.extend(documents)

    def store_chunks(self, chunks):
        self.stored_chunks.extend(chunks)

    def mark_inactive_chunks(self, source_paths, active_content_hashes, embedding_model):
        self.inactive_call = (source_paths, active_content_hashes, embedding_model)


class FakeEmbedder:
    def __init__(self):
        self.embedded_texts = []

    def embed(self, texts):
        self.embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self


def test_dry_run_reads_markdown_and_reports_summary(tmp_path: Path):
    corpus = tmp_path / "knowledge" / "seed-documents"
    city_dir = corpus / "cities"
    city_dir.mkdir(parents=True)
    document = city_dir / "toronto-city-overview.md"
    document.write_text(
        "\n".join(
            [
                "# Toronto City Overview",
                "",
                "## Metadata",
                "",
                "city: Toronto",
                "category: city-overview",
                "confidence: medium",
                "",
                "## City Snapshot",
                "",
                "Toronto is a compact host city for retrieval tests.",
            ]
        )
    )

    settings = IngestionSettings(corpus_root=corpus)
    summary = IngestionPipeline(settings=settings).run(dry_run=True)

    assert summary.documents_read == 1
    assert summary.chunks_created == 1
    assert summary.chunks_skipped == 0
    assert summary.chunks_to_embed == 1
    assert summary.chunks_embedded == 0
    assert summary.embedding_model == "text-embedding-004"
    assert summary.estimated_cost_usd > 0
    assert summary.documents[0].source_path == "cities/toronto-city-overview.md"
    assert summary.documents[0].category == "cities"
    assert summary.documents[0].title == "Toronto City Overview"


def test_chunking_and_hashing_are_deterministic():
    content = "\n\n".join(
        [
            "# Guide",
            "## First Section",
            "alpha " * 460,
            "## Second Section",
            "beta " * 20,
        ]
    )

    first_run = chunk_markdown(content, max_words=120)
    second_run = chunk_markdown(content, max_words=120)

    assert [(chunk.chunk_index, chunk.text, chunk.content_hash) for chunk in first_run] == [
        (chunk.chunk_index, chunk.text, chunk.content_hash) for chunk in second_run
    ]
    assert [chunk.chunk_index for chunk in first_run] == list(range(len(first_run)))
    assert len(first_run) > 1
    assert content_hash("same   text\nvalue") == content_hash("same text value")
    assert content_hash("same text value") != content_hash("changed text value")


def test_ingestion_skips_existing_chunks_before_embedding(tmp_path: Path):
    corpus = tmp_path / "knowledge" / "seed-documents"
    city_dir = corpus / "cities"
    city_dir.mkdir(parents=True)
    (city_dir / "first.md").write_text("# First\n\nFresh content for embedding.")
    (city_dir / "second.md").write_text("# Second\n\nExisting content.")

    existing_hash = chunk_markdown("# Second\n\nExisting content.")[0].content_hash
    store = FakeStore(existing_hashes={existing_hash})
    embedder = FakeEmbedder()

    summary = IngestionPipeline(
        settings=IngestionSettings(corpus_root=corpus),
        store=store,
        embedder=embedder,
    ).run()

    assert summary.chunks_created == 2
    assert summary.chunks_skipped == 1
    assert summary.chunks_to_embed == 1
    assert summary.chunks_embedded == 1
    assert len(embedder.embedded_texts) == 1
    assert "Fresh content" in embedder.embedded_texts[0]
    assert len(store.stored_chunks) == 1
    assert store.upserted_documents


def test_ingestion_populates_retrieval_metadata_and_chunk_text(tmp_path: Path):
    corpus = tmp_path / "knowledge" / "seed-documents"
    hotspot_dir = corpus / "fan-hotspots"
    hotspot_dir.mkdir(parents=True)
    (hotspot_dir / "toronto-fan-hotspots.md").write_text(
        "\n".join(
            [
                "# Toronto Fan Hotspots",
                "",
                "## Metadata",
                "",
                "city: Toronto",
                "team: Argentina",
                "source_type: partner",
                "",
                "## Supporter Signals",
                "",
                "Supporters gather near transit and downtown pubs.",
            ]
        )
    )
    store = FakeStore()
    embedder = FakeEmbedder()

    IngestionPipeline(
        settings=IngestionSettings(corpus_root=corpus),
        store=store,
        embedder=embedder,
    ).run()

    document = store.upserted_documents[0]
    assert document.city_id == "city_toronto"
    assert document.team_id == "team_argentina"
    assert document.source_type == "partner"
    assert store.stored_chunks[0]["chunk_text"] == embedder.embedded_texts[0]
    assert "content" not in store.stored_chunks[0]


def test_postgres_store_uses_document_scoped_chunk_upsert_conflict():
    connection = RecordingConnection()
    store = PostgresDocumentStore("postgresql://example")
    store._document_ids["cities/toronto.md"] = "00000000-0000-0000-0000-000000000001"
    store._connect = lambda: connection

    store.store_chunks(
        [
            {
                "source_path": "cities/toronto.md",
                "category": "cities",
                "title": "Toronto",
                "chunk_index": 0,
                "chunk_text": "Toronto retrieval context.",
                "content_hash": "hash-1",
                "embedding_model": "text-embedding-004",
                "embedding": [0.1, 0.2, 0.3],
            }
        ]
    )

    sql = connection.statements[0][0].lower()
    assert "on conflict (document_id, content_hash, embedding_model)" in sql


def test_embedding_cost_uses_billable_characters_for_new_chunks_only():
    estimate = estimate_embedding_cost(
        ["a" * 1000, "b" * 1500],
        embedding_model="text-embedding-004",
        price_per_1k_chars=0.000025,
    )

    assert estimate.billable_characters == 2500
    assert estimate.price_per_1k_chars == 0.000025
    assert estimate.estimated_cost_usd == 0.0000625


def test_real_ingestion_requires_store_and_embedder(tmp_path: Path):
    corpus = tmp_path / "knowledge" / "seed-documents"
    corpus.mkdir(parents=True)
    (corpus / "doc.md").write_text("# Doc\n\nContent")

    with pytest.raises(IngestionConfigurationError, match="store and embedder"):
        IngestionPipeline(settings=IngestionSettings(corpus_root=corpus)).run()


def test_supabase_schema_defines_documents_and_chunks():
    schema = Path("supabase/migrations/202605270602_create_document_ingestion_tables.sql")

    sql = schema.read_text()

    assert "create extension if not exists vector" in sql.lower()
    assert "create table if not exists documents" in sql.lower()
    assert "create table if not exists document_chunks" in sql.lower()
    assert "content_hash" in sql
    assert "embedding_model" in sql
    assert "vector(768)" in sql
    assert "unique" in sql.lower()


def test_supabase_rag_schema_exposes_vector_retrieval_contract():
    schema = Path("supabase/migrations/202606030603_expand_rag_schema.sql")

    sql = schema.read_text().lower()

    assert "alter table documents" in sql
    assert "city_id" in sql
    assert "team_id" in sql
    assert "source_type" in sql
    assert "rename column content to chunk_text" in sql
    assert "create table if not exists retrieval_logs" in sql
    assert "retrieval_strategy text not null default 'vector'" in sql
    assert "create or replace function match_document_chunks" in sql
    assert "match_count integer default 5" in sql
    assert "filter_city_id text default null" in sql
    assert "filter_team_id text default null" in sql
    assert "filter_category text default null" in sql
    assert "filter_source_type text default null" in sql
    assert "1 - (dc.embedding <=> query_embedding)" in sql
    assert "insert into retrieval_logs" in sql
    assert "source_path" in sql
