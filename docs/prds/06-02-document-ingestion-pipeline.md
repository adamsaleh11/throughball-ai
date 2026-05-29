# PRD: Document Ingestion Pipeline

## Problem Statement

WorldPulse has a curated markdown corpus under the knowledge seed document tree, but there is not yet a repeatable way to turn that source knowledge into retrievable vector data. The current `search_documents` tool is still seeded, so downstream agents can be shaped around evidence retrieval but cannot yet search the real corpus.

This matters because the RAG layer is the grounding bridge between curated human-readable knowledge and AI synthesis. The ingestion path must preserve the repo's low-cost, orchestration-first philosophy: deterministic preprocessing belongs in backend code, embeddings are generated only when source content changes, and no Gemini call should be involved in ingestion.

Without a local ingestion pipeline, developers cannot reliably populate Supabase pgvector, validate idempotency, estimate embedding cost before paid work, or prevent duplicate embedding of unchanged chunks.

## Solution

Build a local, manually invoked ingestion pipeline that reads curated markdown files recursively, extracts document metadata, chunks documents deterministically, generates stable content hashes, embeds only new chunk content through Vertex AI text embeddings, and stores document and chunk records in Supabase pgvector.

The pipeline should be safe to re-run. A second run over unchanged source files must not duplicate chunks and must not regenerate embeddings for chunk content that already exists for the configured embedding model. The script should provide a dry-run mode so developers can inspect documents, chunks, skipped chunks, billable characters, and estimated cost without requiring Supabase or Google Cloud credentials.

The pipeline should create or document the required Supabase schema as code so the acceptance criteria are reproducible. The schema should support one row per source document and one row per stored chunk, including the source path, category, title, chunk index, content hash, embedding model, vector embedding, and operational timestamps or active-state fields needed to avoid stale retrieval.

## User Stories

1. As a developer, I want to run document ingestion manually from the command line, so that embeddings are not generated during normal app startup.
2. As a developer, I want ingestion to read markdown files recursively from the seed corpus, so that all curated source documents can be loaded without maintaining a manual file list.
3. As a developer, I want files processed in deterministic order, so that chunk indexes and logs are stable across runs.
4. As a developer, I want metadata extracted from the existing markdown metadata block, so that ingestion can use the current corpus format without forcing frontmatter churn.
5. As a developer, I want metadata derived from file path and filename when needed, so that documents still have source path, category, and title even if optional metadata is missing.
6. As a developer, I want each source markdown file represented as a document record, so that retrieval results can point back to the curated source.
7. As a developer, I want each document chunk represented as a chunk record, so that vector search can retrieve focused evidence instead of whole documents.
8. As a developer, I want chunking to be deterministic and section-aware, so that small edits produce predictable chunk changes.
9. As a developer, I want oversized sections split by a stable text budget, so that every chunk stays within the embedding model's input limits.
10. As a developer, I want chunk indexes to be stable within each source document, so that retrieval citations can identify chunk order.
11. As a developer, I want a content hash generated for each normalized chunk, so that duplicate embedding work can be skipped reliably.
12. As a developer, I want unchanged chunks skipped before any Vertex AI call, so that rerunning ingestion does not create unnecessary paid requests.
13. As a developer, I want duplicate chunk rows prevented by database constraints, so that script bugs or concurrent runs do not create duplicate retrieval data.
14. As a developer, I want embedding model stored with each chunk, so that future model migrations can coexist with previous embeddings.
15. As a developer, I want the embedding price configurable by environment variable, so that cost estimates can track Google pricing changes without code changes.
16. As a developer, I want estimated embedding cost calculated from billable input characters for only new chunks, so that logs reflect the actual expected paid work for the run.
17. As a developer, I want dry-run mode, so that I can validate discovery, chunking, skip counts, and estimated cost without writing to Supabase or calling Vertex AI.
18. As a developer, I want missing Supabase credentials to fail clearly for real ingestion, so that configuration problems are discovered before partial writes.
19. As a developer, I want missing Google Cloud configuration or auth to fail clearly before embedding, so that paid-provider failures do not appear as successful ingestion.
20. As a developer, I want Vertex AI text embeddings used through Google Cloud authentication, so that the pipeline follows the repo's existing Google Cloud boundary.
21. As an operator, I want the cheapest supported configured text embedding model used by default, so that the prototype remains low-cost.
22. As an operator, I want the model configurable, so that the ingestion pipeline can move from `text-embedding-004` to a newer supported text embedding model without a redesign.
23. As an operator, I want logs to show documents read, chunks created, chunks skipped, chunks embedded, billable characters, and estimated cost, so that each run is auditable.
24. As an operator, I want logs to avoid full chunk text or prompt dumps, so that observability stays compact and source content is not duplicated into logs.
25. As a reviewer, I want unit tests for metadata extraction, chunking, content hashing, and skip behavior, so that the deterministic parts are covered without paid services.
26. As a reviewer, I want ingestion tests to use fake embedding and database adapters, so that CI never requires live Supabase or Vertex credentials.
27. As a reviewer, I want schema constraints checked in with the repo, so that table shape and idempotency rules are reviewable.
28. As an agent developer, I want ingested chunks to preserve source path, category, title, and confidence/source metadata where available, so that future retrieval tools can cite evidence clearly.
29. As an agent developer, I want stale chunks handled without destructive deletion, so that changed source documents do not keep obsolete chunks active in retrieval.
30. As a maintainer, I want ingestion separated from MCP search integration, so that this ticket can focus on reliable storage before changing retrieval behavior.

## Implementation Decisions

- The ingestion pipeline will be a local command-line workflow, not an app startup hook.
- Source input is the curated markdown corpus under the knowledge seed document tree, discovered recursively with a stable lexicographic order.
- The existing markdown `## Metadata` block remains the source metadata contract. YAML frontmatter is not required for this ticket.
- Metadata extraction will combine parsed markdown metadata with path-derived fallbacks. The stable fields are source path, category, title, and optional source/confidence metadata when present.
- The pipeline will build or modify a dedicated ingestion module with separate responsibilities for orchestration, chunking, embeddings, and metadata extraction.
- Chunking will be deterministic and markdown-aware. It should prefer section boundaries, then split oversized sections by a stable paragraph or word budget.
- Chunk overlap should be avoided when sections fit. A small deterministic overlap is acceptable only when forced splits are needed.
- Each chunk will receive a stable content hash derived from normalized chunk text and a chunking version. Metadata-only edits should not force re-embedding identical chunk text.
- Supabase pgvector is the vector store for this prototype. Vertex Vector Search is explicitly not used.
- The repository should include schema-as-code for the required Supabase tables so ingestion can be reproduced in a new environment.
- The `documents` table represents source markdown files. `source_path` is the natural key.
- The `document_chunks` table represents stored chunks. It stores source path linkage, category, title, chunk index, content hash, embedding model, vector embedding, and active or last-seen state.
- Duplicate embedding should be prevented by checking for existing chunk content by content hash and embedding model before calling Vertex AI.
- Database constraints should prevent duplicate active chunk records for the same content hash and embedding model.
- Changed documents should upsert document metadata, insert new chunk hashes, and mark no-longer-seen chunks inactive rather than destructively deleting them.
- The default embedding model should be configurable and should use the cheapest supported Vertex AI text embedding model available for the environment. `text-embedding-004` remains acceptable when configured, but the implementation should not assume it is the only supported model.
- Vertex AI embeddings will be called through Google Cloud authentication using the existing Google Cloud project and location configuration.
- The embedding task type should be document retrieval when supported by the selected model.
- The embedding dimensionality must match the pgvector schema. For `text-embedding-004` and similar text embedding models, the expected prototype dimension is 768 unless a configured model requires a different schema.
- The pipeline should fail fast if the configured model's output dimensionality cannot be stored in the configured pgvector column.
- Estimated embedding cost is calculated from billable input characters for chunks that will actually be embedded, not skipped chunks.
- The default online embedding price is `$0.000025` per 1,000 input characters, with a configurable environment override because Google pricing can change.
- Batch embedding pricing may be represented as a separate configurable value, but this prototype should estimate online request cost unless the implementation actually uses batch requests.
- Cost logging should include embedding model, chunks to embed, billable characters, price per 1,000 characters, and estimated cost in USD.
- The ingestion command should support a dry-run mode that performs discovery, metadata extraction, chunking, hash generation, skip analysis when possible, and cost estimation without paid embedding calls or writes.
- The ingestion command may support optional limit/root arguments for local testing, but the stable default should ingest the full seed corpus.
- Supabase writes should use a backend credential suitable for ingestion, such as a database URL or service-role-backed connection. Secrets must come from environment variables and must not be logged.
- Direct Postgres access is acceptable for pgvector writes if it keeps vector serialization and constraints simpler than the Supabase REST client.
- Logs should be compact structured summaries and should not duplicate full chunk text, full prompts, or vector payloads.
- The `search_documents` MCP tool is not updated in this ticket unless a future ticket explicitly connects retrieval to Supabase pgvector.

## Testing Decisions

- Tests should cover deterministic behavior and external contracts, not implementation details such as private helper names.
- Metadata tests should verify that existing markdown metadata blocks are parsed and that category/title/source-path fallbacks are derived from paths.
- Chunking tests should verify deterministic ordering, stable chunk indexes, section-aware splitting, and stable output across repeated runs.
- Hashing tests should verify that identical normalized chunk text produces the same content hash and changed chunk text produces a different hash.
- Cost-estimation tests should verify character-based pricing, configurable price per 1,000 characters, and exclusion of skipped chunks from billable character counts.
- Skip-behavior tests should use a fake database adapter that reports existing content hashes and assert that existing chunks are not sent to the embedding adapter.
- Ingestion orchestration tests should use fake embedding and database adapters so no test requires live Supabase, Vertex AI, Google Cloud credentials, or external network access.
- Dry-run tests should verify that dry-run completes without credentials, performs no writes, performs no embedding calls, and returns/logs the expected summary counts.
- Schema tests should verify that the checked-in SQL includes pgvector support, the two required tables, embedding model fields, content hash fields, and uniqueness constraints needed for idempotency.
- Existing corpus validation tests should continue to pass. This ingestion ticket should not add generated embeddings, vector indexes, chunk exports, or database dumps to the knowledge corpus.

## Out of Scope

- Updating the MCP `search_documents` tool to query Supabase pgvector.
- Building a full retrieval API or ranking layer.
- Running ingestion automatically on app startup.
- Calling Gemini or any generative model during ingestion.
- Using Gemini embedding models unless explicitly configured and priced separately.
- Using Vertex Vector Search.
- Scraping new source content or changing the curated markdown corpus.
- Committing generated embeddings, vector files, chunk exports, database dumps, FAISS indexes, SQLite files, or other retrieval artifacts.
- Implementing deterministic ranking, filtering, hotspot scoring, itinerary ordering, or AI synthesis.
- Production deployment automation for Supabase migrations.
- Full model migration tooling for re-embedding an existing corpus with a new embedding model.

## Further Notes

- Google Cloud pricing should be treated as mutable. The current confirmed pricing for non-Gemini Vertex AI text embeddings is `$0.000025` per 1,000 input characters for online requests and `$0.00002` per 1,000 input characters for batch requests, but the code should keep pricing configurable.
- Cost estimates should be described as estimates because Google billing rules, counted characters, regional pricing, and model availability can change.
- The current corpus is small enough that first-run embedding should cost pennies, but idempotency is still required because this repo demonstrates production AI systems discipline rather than one-off scripts.
- The current Vertex AI text embeddings documentation emphasizes newer model IDs such as `text-embedding-005`, `text-multilingual-embedding-002`, and `gemini-embedding-001`. The implementation should preserve a configurable model boundary rather than baking in an obsolete model ID.
- The strongest implementation risk is mixing too many concerns into the script entrypoint. The ingestion command should coordinate deeper modules that own metadata parsing, chunking, embedding, storage, and cost estimation behind stable interfaces.
