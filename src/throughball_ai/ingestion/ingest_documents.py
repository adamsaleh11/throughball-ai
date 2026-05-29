import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from throughball_ai.ingestion.chunking import DocumentChunk, chunk_markdown
from throughball_ai.ingestion.embeddings import (
    ONLINE_EMBEDDING_PRICE_PER_1K_CHARS,
    VertexTextEmbeddingClient,
    estimate_embedding_cost,
)
from throughball_ai.ingestion.metadata import DocumentMetadata, extract_metadata


@dataclass(frozen=True)
class IngestionSettings:
    corpus_root: Path = Path("knowledge/seed-documents")
    embedding_model: str = "text-embedding-004"
    embedding_price_per_1k_chars: float = ONLINE_EMBEDDING_PRICE_PER_1K_CHARS
    supabase_db_url: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str | None = None

    @classmethod
    def from_env(cls, corpus_root: Path | None = None) -> "IngestionSettings":
        return cls(
            corpus_root=corpus_root or Path(os.getenv("INGESTION_CORPUS_ROOT", "knowledge/seed-documents")),
            embedding_model=os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-004"),
            embedding_price_per_1k_chars=float(
                os.getenv(
                    "EMBEDDING_PRICE_PER_1K_CHARS",
                    str(ONLINE_EMBEDDING_PRICE_PER_1K_CHARS),
                )
            ),
            supabase_db_url=os.getenv("SUPABASE_DB_URL"),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION"),
        )


@dataclass(frozen=True)
class IngestedDocument:
    metadata: DocumentMetadata
    chunks: list[DocumentChunk]

    @property
    def source_path(self) -> str:
        return self.metadata.source_path

    @property
    def category(self) -> str:
        return self.metadata.category

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def city_id(self) -> str | None:
        return self.metadata.city_id

    @property
    def team_id(self) -> str | None:
        return self.metadata.team_id

    @property
    def source_type(self) -> str:
        return self.metadata.source_type


@dataclass(frozen=True)
class IngestionSummary:
    documents_read: int
    chunks_created: int
    chunks_skipped: int
    chunks_to_embed: int
    chunks_embedded: int
    billable_characters: int
    price_per_1k_chars: float
    estimated_cost_usd: float
    embedding_model: str
    documents: list[IngestedDocument] = field(default_factory=list)

    def to_log_dict(self) -> dict:
        return {
            "embedding_model": self.embedding_model,
            "documents_read": self.documents_read,
            "chunks_created": self.chunks_created,
            "chunks_skipped": self.chunks_skipped,
            "chunks_to_embed": self.chunks_to_embed,
            "chunks_embedded": self.chunks_embedded,
            "billable_characters": self.billable_characters,
            "price_per_1k_chars": self.price_per_1k_chars,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


class IngestionConfigurationError(RuntimeError):
    """Raised when a real ingestion run is missing required external adapters."""


class DocumentStore(Protocol):
    def existing_content_hashes(
        self,
        content_hashes: set[str],
        embedding_model: str,
    ) -> set[str]:
        ...

    def upsert_documents(self, documents: list[IngestedDocument]) -> None:
        ...

    def store_chunks(self, chunks: list[dict]) -> None:
        ...

    def mark_inactive_chunks(
        self,
        source_paths: set[str],
        active_content_hashes: set[str],
        embedding_model: str,
    ) -> None:
        ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class IngestionPipeline:
    def __init__(
        self,
        settings: IngestionSettings | None = None,
        store: DocumentStore | None = None,
        embedder: Embedder | None = None,
    ):
        self.settings = settings or IngestionSettings()
        self.store = store
        self.embedder = embedder

    def run(self, dry_run: bool = False) -> IngestionSummary:
        if not dry_run and (self.store is None or self.embedder is None):
            raise IngestionConfigurationError(
                "Real ingestion requires a document store and embedder. Use dry_run=True "
                "to inspect the corpus without Supabase or Vertex AI credentials."
            )
        documents = self._load_documents()
        chunks = [chunk for document in documents for chunk in document.chunks]
        existing_hashes: set[str] = set()
        if not dry_run and self.store is not None:
            existing_hashes = self.store.existing_content_hashes(
                {chunk.content_hash for chunk in chunks},
                self.settings.embedding_model,
            )
        skipped_chunks = [chunk for chunk in chunks if chunk.content_hash in existing_hashes]
        chunks_to_embed = [
            (document, chunk)
            for document in documents
            for chunk in document.chunks
            if chunk.content_hash not in existing_hashes
        ]
        estimate = estimate_embedding_cost(
            [chunk.text for _, chunk in chunks_to_embed],
            embedding_model=self.settings.embedding_model,
            price_per_1k_chars=self.settings.embedding_price_per_1k_chars,
        )
        if not dry_run and self.store is not None:
            self.store.upsert_documents(documents)
            embeddings = self.embedder.embed([chunk.text for _, chunk in chunks_to_embed]) if self.embedder else []
            self.store.store_chunks(
                [
                    {
                        "source_path": document.source_path,
                        "category": document.category,
                        "title": document.title,
                        "chunk_index": chunk.chunk_index,
                        "content_hash": chunk.content_hash,
                        "embedding_model": self.settings.embedding_model,
                        "chunk_text": chunk.text,
                        "embedding": embedding,
                    }
                    for (document, chunk), embedding in zip(chunks_to_embed, embeddings)
                ]
            )
            self.store.mark_inactive_chunks(
                {document.source_path for document in documents},
                {chunk.content_hash for chunk in chunks},
                self.settings.embedding_model,
            )
        return IngestionSummary(
            documents_read=len(documents),
            chunks_created=len(chunks),
            chunks_skipped=len(skipped_chunks),
            chunks_to_embed=len(chunks_to_embed),
            chunks_embedded=0 if dry_run else len(chunks_to_embed),
            billable_characters=estimate.billable_characters,
            price_per_1k_chars=estimate.price_per_1k_chars,
            estimated_cost_usd=estimate.estimated_cost_usd,
            embedding_model=estimate.embedding_model,
            documents=documents,
        )

    def _load_documents(self) -> list[IngestedDocument]:
        root = self.settings.corpus_root
        documents: list[IngestedDocument] = []
        for path in sorted(root.rglob("*.md")):
            content = path.read_text(encoding="utf-8")
            metadata = extract_metadata(path=path, corpus_root=root, content=content)
            documents.append(
                IngestedDocument(
                    metadata=metadata,
                    chunks=chunk_markdown(content),
                )
            )
        return documents


class PostgresDocumentStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._document_ids: dict[str, str] = {}

    def existing_content_hashes(
        self,
        content_hashes: set[str],
        embedding_model: str,
    ) -> set[str]:
        if not content_hashes:
            return set()
        with self._connect() as connection:
            rows = connection.execute(
                """
                select content_hash
                from document_chunks
                where embedding_model = %s
                  and content_hash = any(%s)
                  and is_active = true
                """,
                (embedding_model, list(content_hashes)),
            ).fetchall()
        return {row[0] for row in rows}

    def upsert_documents(self, documents: list[IngestedDocument]) -> None:
        if not documents:
            return
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            for document in documents:
                row = connection.execute(
                    """
                    insert into documents (
                        source_path,
                        category,
                        title,
                        city_id,
                        team_id,
                        source_type,
                        metadata,
                        updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, now())
                    on conflict (source_path) do update set
                        category = excluded.category,
                        title = excluded.title,
                        city_id = excluded.city_id,
                        team_id = excluded.team_id,
                        source_type = excluded.source_type,
                        metadata = excluded.metadata,
                        updated_at = now()
                    returning id
                    """,
                    (
                        document.source_path,
                        document.category,
                        document.title,
                        document.city_id,
                        document.team_id,
                        document.source_type,
                        Jsonb(document.metadata.fields),
                    ),
                ).fetchone()
                self._document_ids[document.source_path] = str(row[0])

    def store_chunks(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        with self._connect() as connection:
            for chunk in chunks:
                document_id = self._document_ids[chunk["source_path"]]
                connection.execute(
                    """
                    insert into document_chunks (
                        document_id,
                        source_path,
                        category,
                        title,
                        chunk_index,
                        chunk_text,
                        content_hash,
                        embedding_model,
                        embedding,
                        is_active,
                        last_seen_at,
                        updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, now(), now())
                    on conflict (document_id, content_hash, embedding_model) do update set
                        is_active = true,
                        last_seen_at = now(),
                        updated_at = now()
                    """,
                    (
                        document_id,
                        chunk["source_path"],
                        chunk["category"],
                        chunk["title"],
                        chunk["chunk_index"],
                        chunk["chunk_text"],
                        chunk["content_hash"],
                        chunk["embedding_model"],
                        _format_vector(chunk["embedding"]),
                    ),
                )

    def mark_inactive_chunks(
        self,
        source_paths: set[str],
        active_content_hashes: set[str],
        embedding_model: str,
    ) -> None:
        if not source_paths:
            return
        with self._connect() as connection:
            connection.execute(
                """
                update document_chunks
                set is_active = false, updated_at = now()
                where embedding_model = %s
                  and source_path = any(%s)
                  and not (content_hash = any(%s))
                """,
                (embedding_model, list(source_paths), list(active_content_hashes)),
            )

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, prepare_threshold=None)


def _format_vector(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def build_pipeline(settings: IngestionSettings, dry_run: bool) -> IngestionPipeline:
    if dry_run:
        return IngestionPipeline(settings=settings)
    if not settings.supabase_db_url:
        raise IngestionConfigurationError("SUPABASE_DB_URL is required for real ingestion.")
    if not settings.google_cloud_project or not settings.google_cloud_location:
        raise IngestionConfigurationError(
            "GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are required for real ingestion."
        )
    return IngestionPipeline(
        settings=settings,
        store=PostgresDocumentStore(settings.supabase_db_url),
        embedder=VertexTextEmbeddingClient(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            model_name=settings.embedding_model,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest curated markdown documents into Supabase pgvector.")
    parser.add_argument("--root", type=Path, default=None, help="Corpus root. Defaults to INGESTION_CORPUS_ROOT.")
    parser.add_argument("--dry-run", action="store_true", help="Skip Supabase writes and Vertex embedding calls.")
    args = parser.parse_args(argv)

    settings = IngestionSettings.from_env(corpus_root=args.root)
    pipeline = build_pipeline(settings=settings, dry_run=args.dry_run)
    summary = pipeline.run(dry_run=args.dry_run)
    print(json.dumps(summary.to_log_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
