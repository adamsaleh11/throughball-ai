# PRD: Supabase Vector Retrieval Schema

## Problem Statement

WorldPulse has a deterministic document ingestion pipeline and an initial Supabase pgvector schema, but the database is not yet shaped as a retrieval contract. The existing tables can store documents and embeddings, yet they do not fully expose the metadata filters, retrieval logging, source paths, and stable RPC surface needed for RAG-backed agent evidence.

This matters because downstream agents should explain, synthesize, and cite retrieved evidence while deterministic filtering and vector matching stay in the backend. Without a proper Supabase retrieval schema, the project risks mixing retrieval semantics into MCP stubs or agent prompts, losing citation provenance, and missing the observability needed to evaluate retrieval quality and latency.

The schema also needs to evolve like a production system. The existing migration and ingestion behavior should be preserved through a forward migration rather than rewritten, so the repo demonstrates realistic database evolution and avoids hidden drift between ingestion and retrieval.

## Solution

Create a forward Supabase migration that expands the existing document ingestion schema into a retrieval-ready RAG schema. The migration should enable pgvector if needed, preserve the existing documents and chunks tables, add normalized metadata columns for filtering, standardize stored chunk text under the `chunk_text` concept, add retrieval logs, and define a vector similarity RPC named `match_document_chunks`.

The RPC should accept a query embedding, a bounded top-k value defaulting to 5, optional exact-match metadata filters, and optional query text for logging. It should return focused chunk evidence with document metadata, source paths, and cosine similarity scores so agents and MCP tools can cite grounded evidence without performing deterministic ranking or filtering themselves.

Retrieval logging should happen inside the RPC for successful retrievals. Logs should stay compact and operationally useful: query text, top-k, filters, latency, result count, retrieval strategy, and creation time. The schema should support low-cost local development and future observability without adding external vector databases, BigQuery, Vertex Vector Search, or runtime agent wiring in this ticket.

## User Stories

1. As an agent developer, I want source documents stored with normalized retrieval metadata, so that MCP retrieval can filter evidence predictably.
2. As an agent developer, I want document chunks stored with a clear chunk text field, so that retrieval results are unambiguous and easy to cite.
3. As an agent developer, I want vector similarity search exposed through a stable database RPC, so that runtime tools do not duplicate SQL retrieval logic.
4. As an agent developer, I want retrieval results to include source paths, so that AI answers can cite or reference the source evidence.
5. As an agent developer, I want retrieval results to include document title, category, city, team, and source type, so that synthesis can explain evidence context.
6. As an agent developer, I want retrieval results to include similarity scores, so that downstream confidence systems can use deterministic retrieval quality signals.
7. As a backend developer, I want filters for city, team, category, and source type, so that irrelevant documents can be excluded before AI synthesis.
8. As a backend developer, I want filters to be exact-match for this slice, so that the first retrieval contract stays simple and predictable.
9. As a backend developer, I want `top_k` to default to 5, so that retrieval stays low-cost and context stays compact.
10. As a backend developer, I want requested result counts to be bounded, so that callers cannot accidentally retrieve excessive context.
11. As a backend developer, I want inactive chunks excluded from retrieval, so that stale source content does not appear in evidence.
12. As a backend developer, I want existing ingestion history preserved through a forward migration, so that schema evolution remains production-like.
13. As a backend developer, I want ingestion updated for the standardized chunk text field, so that writes and reads use the same schema contract.
14. As a backend developer, I want city and team identifiers stored as text IDs, so that seeded datasets, MCP traces, and demos are easy to inspect.
15. As a backend developer, I want source type stored as a normalized field, so that seeded, cached, partner, external, and verified sources can be separated later.
16. As a backend developer, I want metadata JSON preserved alongside normalized columns, so that future source-specific enrichment does not require immediate schema churn.
17. As a backend developer, I want duplicate chunks scoped by document, content hash, and embedding model, so that identical boilerplate still preserves citation provenance.
18. As an operator, I want successful retrievals logged automatically, so that observability does not depend on every caller remembering to log.
19. As an operator, I want retrieval logs to include filters and result counts, so that retrieval behavior can be audited without dumping full prompts or vectors.
20. As an operator, I want retrieval logs to include latency measured inside the database RPC, so that database retrieval performance can be monitored.
21. As an operator, I want retrieval logs to include retrieval strategy, so that future vector, hybrid, keyword, reranked, or cached behavior can be compared.
22. As a reviewer, I want schema tests or checks for the RPC and required fields, so that acceptance criteria can be validated without a live production database.
23. As a reviewer, I want tests to verify ingestion compatibility after the chunk text rename, so that the migration does not silently break document loading.
24. As a reviewer, I want acceptance checks for metadata filters, so that city, team, category, and source type constraints are not just declared but actually represented in the RPC.
25. As a maintainer, I want this ticket to stop before MCP and agent runtime wiring, so that database retrieval can be reviewed independently.

## Implementation Decisions

- The existing initial Supabase migration will not be rewritten. This work uses a new forward migration that evolves the current schema.
- The existing documents and document chunks tables remain the durable storage boundary for RAG source material.
- The documents table will expose normalized nullable `city_id` and `team_id` fields as text identifiers.
- The documents table will expose `source_type` as a normalized text field defaulting to `seeded`.
- The documents table will keep metadata JSON for flexible source-specific enrichment.
- Text identifiers such as `city_toronto` and `team_argentina` are preferred over UUID-backed domain IDs for seeded metadata because they improve debugging, demos, traces, and MCP tool readability.
- The document chunks table will standardize on the `chunk_text` concept instead of the older generic content naming.
- Ingestion must be updated in the same ticket so chunk writes target the standardized chunk text schema.
- The document chunks table keeps operational state needed for idempotent ingestion and stale chunk handling, including active state and update timestamps.
- Both documents and document chunks should support update timestamps for future refresh jobs, stale chunk cleanup, embedding migrations, and observability.
- Chunk uniqueness should preserve provenance by scoping content hash uniqueness to document, content hash, and embedding model.
- Embeddings remain stored in Supabase pgvector. The expected prototype vector dimension remains 768 for the configured text embedding model.
- The vector similarity RPC will be named `match_document_chunks`.
- The RPC will accept a query embedding, a top-k value defaulting to 5, exact-match metadata filters for city, team, category, and source type, and optional query text for retrieval logging.
- The RPC should cap the effective result count to a small bounded maximum even if callers request more.
- The RPC will search active chunks only.
- Similarity should be returned as cosine similarity derived from the pgvector cosine distance operator.
- RPC results should include chunk ID, document ID, chunk text, chunk index, title, category, city ID, team ID, source type, source path, and similarity score.
- Successful retrievals should be logged inside the RPC.
- Retrieval logs should store query text, effective top-k, filters as JSON, latency in milliseconds, result count, retrieval strategy, and creation time.
- The initial retrieval strategy value is `vector`.
- Retrieval logging should remain compact and should not store query embeddings, result embeddings, full prompts, or verbose traces.
- Runtime access to the retrieval database will later go through MCP, but wiring the MCP `search_documents` tool to this RPC is out of scope for this ticket.
- No external vector database, Vertex Vector Search, BigQuery, or generated vector artifact should be introduced.

## Testing Decisions

- Tests should validate behavior and contracts that matter to retrieval, not private SQL formatting preferences.
- Schema checks should verify pgvector enablement, the required document fields, the required chunk fields, retrieval logs, and the `match_document_chunks` RPC.
- Schema checks should verify the RPC accepts or represents filters for city, team, category, and source type.
- Schema checks should verify the RPC returns source path and document metadata needed for citation.
- Schema checks should verify retrieval logging fields include filters, latency, result count, and retrieval strategy.
- Ingestion tests should be updated to verify the standardized chunk text field is written through the storage boundary.
- Tests should cover that top-k defaults to 5 and that the retrieval count is bounded.
- Tests should cover that inactive chunks are excluded from retrieval, either through SQL contract checks or an integration-style database test if a local Supabase/Postgres harness exists.
- CI should not require a live Supabase project, Google Cloud credentials, Vertex AI, BigQuery, Vertex Vector Search, or any external vector database.
- Existing ingestion, corpus, MCP, telemetry, and runtime boundary tests should continue to pass.

## Out of Scope

- Rewriting the existing initial ingestion migration.
- Replacing Supabase pgvector with Vertex Vector Search, BigQuery, FAISS, Pinecone, Weaviate, or another external vector database.
- Wiring the MCP `search_documents` tool to live Supabase retrieval.
- Updating agents, ADK orchestration, model prompts, or synthesis behavior.
- Generating embeddings or running the ingestion pipeline against production data.
- Building hybrid search, keyword search, reranking, cached retrieval, or query expansion.
- Adding multi-value filter arrays or fallback retrieval expansion.
- Implementing deterministic ranking beyond vector similarity and exact-match filters.
- Storing query embeddings, result embeddings, full prompts, or verbose traces in retrieval logs.
- Adding user-facing UI, admin dashboards, or deployment automation.

## Further Notes

- This ticket intentionally treats database retrieval as the source of deterministic filtering and evidence selection. AI layers should consume retrieved evidence and explain it, not calculate metadata filters or source ranking themselves.
- The forward migration should be careful around the existing chunk content column so that existing ingestion behavior can be evolved without losing stored chunks.
- If a real database integration harness is not available, static SQL checks plus ingestion unit tests are acceptable for this slice. A later integration ticket can exercise the RPC against a local Supabase stack.
- The schema should stay small and understandable. The goal is production-style retrieval infrastructure for a low-cost orchestration project, not a heavyweight analytics platform.
