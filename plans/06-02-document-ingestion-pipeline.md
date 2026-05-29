# Plan: Document Ingestion Pipeline

> Source PRD: docs/prds/06-02-document-ingestion-pipeline.md

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no HTTP route is required. Ingestion is a manually invoked local command, not app startup behavior.
- **Schema**: Supabase pgvector stores source documents and document chunks. Source documents are keyed by source path. Chunks store category, title, chunk index, content hash, embedding model, vector embedding, and active or last-seen state for stale chunk handling.
- **Key models**: source document, parsed document metadata, deterministic chunk, content hash, embedding estimate, ingestion summary.
- **Auth**: Supabase and Google Cloud credentials come from environment variables. Dry-run mode must work without credentials.
- **External services**: Vertex AI text embeddings through Google Cloud auth and Supabase Postgres/pgvector for storage. No Gemini calls, no Vertex Vector Search.
- **Cost controls**: only chunks missing for the configured content hash and embedding model are embedded. Estimated cost uses billable input characters, not Gemini token estimates.
- **Observability**: logs contain compact counts, hashes or IDs when useful, model, billable characters, price per 1,000 characters, and estimated cost. Logs do not dump full chunk text or vectors.

---

## Phase 1: Schema And Dry-Run Skeleton

**User stories**: 1-7, 15-18, 23, 27

### What to build

Create the reproducible ingestion surface: schema-as-code for the two Supabase tables, configuration for corpus root, embedding model, and embedding price, plus a local command that can recursively discover markdown files, parse metadata, and report a dry-run summary without credentials, database writes, or embedding calls.

### Acceptance criteria

- [ ] Supabase schema for documents and document chunks is checked in.
- [ ] Dry-run discovers markdown files recursively in stable sorted order.
- [ ] Dry-run extracts source path, category, title, and available metadata from existing markdown files.
- [ ] Dry-run works without Supabase or Google Cloud credentials.
- [ ] Dry-run logs or returns documents read, chunks created, chunks skipped, billable characters, and estimated cost.
- [ ] Tests cover dry-run discovery and metadata extraction through the public ingestion interface.

---

## Phase 2: Deterministic Chunking And Hashing

**User stories**: 8-13, 25, 29

### What to build

Add markdown-aware deterministic chunking and stable content hashes. Chunks should preserve section context where possible, split oversized sections predictably, and produce stable indexes and hashes across repeated runs.

### Acceptance criteria

- [ ] Chunking prefers markdown section boundaries.
- [ ] Oversized sections split by a stable text budget.
- [ ] Chunk indexes are stable within each source document.
- [ ] Content hashes are derived from normalized chunk text and a chunking version.
- [ ] Repeated runs over unchanged content produce the same chunk indexes and hashes.
- [ ] Tests cover deterministic chunking and hash behavior.

---

## Phase 3: Idempotent Storage Without Live Embeddings

**User stories**: 6-7, 12-14, 18, 24, 26-29

### What to build

Wire the ingestion pipeline to a storage boundary that can upsert documents, check existing chunk hashes for the configured embedding model, store newly embedded chunks, and mark no-longer-seen chunks inactive. Drive behavior with fake adapters first so CI remains network-free.

### Acceptance criteria

- [ ] Existing chunk hashes are checked before any embedding request.
- [ ] Existing chunks are counted as skipped and are not sent to the embedding adapter.
- [ ] New chunks are stored with source path, category, title, chunk index, content hash, and embedding model.
- [ ] Changed documents can mark stale chunks inactive instead of deleting them.
- [ ] Tests use fake storage and embedding adapters and require no live Supabase or Vertex credentials.

---

## Phase 4: Vertex Embeddings And Cost Accounting

**User stories**: 15-24, 26

### What to build

Add the real Vertex AI embedding boundary and character-based cost estimation. The pipeline should embed only new chunks, use configurable model and pricing settings, fail clearly when credentials/config are missing for real ingestion, and log compact cost details.

### Acceptance criteria

- [ ] Embedding model is configurable and defaults to the configured cheapest supported text embedding model.
- [ ] Embedding price per 1,000 characters is configurable with an online-request default of 0.000025.
- [ ] Billable characters count only new chunks to embed.
- [ ] Estimated cost equals `(billable_characters / 1000) * price_per_1k_chars`.
- [ ] Real ingestion fails clearly when required Supabase or Google Cloud configuration is missing.
- [ ] Tests cover cost estimation and config failure behavior without live provider calls.

---

## Phase 5: End-To-End Ingestion Acceptance

**User stories**: 1-30

### What to build

Connect the full ingestion command path and verify the acceptance behavior across discovery, metadata, chunking, skip checks, embedding, storage, summaries, and corpus boundary protection.

### Acceptance criteria

- [ ] Running ingestion against a fake or configured store reads source documents, creates chunks, embeds only new chunks, and stores document/chunk records.
- [ ] Re-running ingestion over unchanged content does not duplicate chunks.
- [ ] Re-running ingestion over unchanged content does not regenerate embeddings.
- [ ] Summary output shows documents read, chunks created, chunks skipped, chunks embedded, billable characters, price per 1,000 characters, and estimated cost.
- [ ] Existing corpus validation continues to prevent committed generated artifacts.
- [ ] Full test suite passes without live Supabase, Vertex AI, or external network access.
