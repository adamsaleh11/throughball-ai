# PRD: Search Documents RAG Tool

## Problem Statement

Throughball needs `search_documents` to become the primary retrieval tool for ADK agents. The current tool surface exists, but it still behaves like a seeded stub and does not retrieve evidence from the curated knowledge corpus stored in Supabase pgvector. This leaves downstream agents unable to ground match analysis, fan gathering explanations, city concierge recommendations, and itinerary summaries in retrieved document chunks.

This matters now because the system is moving from tool-contract scaffolding into production-oriented AI orchestration. Agents should explain, synthesize, route, and summarize, but they should not perform deterministic retrieval filtering, ranking, scoring, or document handling themselves. The RAG tool must provide compact, source-backed evidence through MCP while preserving the repo's low-cost, deterministic, orchestration-first constraints.

The affected users are ADK agents, developers building new agents, reviewers evaluating the demo/interview architecture, and operators who need retrieval latency and degraded states to be observable without storing massive documents, embeddings, full prompts, or verbose traces.

## Solution

Implement `search_documents` as a real MCP RAG retrieval tool backed by Supabase pgvector. The tool will accept a query plus optional exact-match metadata filters for city, team, and category, generate a query embedding through the configured internal text-embedding provider, call the Supabase vector RPC, and return bounded evidence chunks with source metadata, similarity scores, retrieval confidence, degraded state, and telemetry.

The tool will remain deterministic and low-cost. It will not call Gemini, perform LLM reranking, use lexical fallback, search external APIs, or return full documents. Backend code will own embedding, metadata filter propagation, RPC parameter construction, confidence calculation, result compaction, and observability. Agents will receive compact chunks and source fields suitable for grounded synthesis.

The implementation will preserve compatibility with the existing MCP contract by continuing to expose `data.results[]` as a derived compatibility shape, while treating the new canonical retrieval fields as the source of truth: chunks, document titles, source paths, similarity scores, retrieval confidence, degraded status, and telemetry.

## User Stories

1. As an ADK agent, I want to call `search_documents` with a natural-language query, so that I can retrieve grounded evidence for synthesis.
2. As an ADK agent, I want retrieved chunks instead of full documents, so that I can stay within compact context and cost boundaries.
3. As an ADK agent, I want each retrieved chunk to include its document title, source path, and similarity score, so that I can cite evidence provenance.
4. As an ADK agent, I want retrieval confidence returned deterministically, so that I can calibrate explanations without inventing certainty.
5. As an ADK agent, I want empty successful retrievals to be represented safely, so that no-match cases do not look like infrastructure failures.
6. As an ADK agent, I want degraded infrastructure failures to return a valid empty retrieval envelope, so that one retrieval outage does not crash the agent flow.
7. As an ADK agent, I want `city_id` to filter retrieval results exactly, so that city-specific questions do not pull unrelated host-city evidence.
8. As an ADK agent, I want `team_id` to filter retrieval results exactly, so that team-specific questions can target relevant team context.
9. As an ADK agent, I want `category` to filter retrieval results exactly, so that city, venue, safety, tourism, transportation, match-preview, and fan-hotspot retrieval can stay focused.
10. As an ADK agent, I want `top_k` to default to 5, so that common calls are concise without extra parameters.
11. As an ADK agent, I want `top_k` capped at 8, so that the tool never returns excessive evidence.
12. As an ADK agent, I want legacy `results` data to remain available, so that older MCP consumers do not break while the RAG contract evolves.
13. As a developer, I want the tool to call the existing Supabase vector RPC, so that retrieval uses the database retrieval contract rather than ad hoc SQL.
14. As a developer, I want query embedding isolated behind an embedding provider interface, so that tests can inject deterministic embeddings without live credentials.
15. As a developer, I want vector RPC access isolated behind a repository interface, so that database failures and parameter propagation can be tested cleanly.
16. As a developer, I want retrieval orchestration isolated in a service interface, so that confidence calculation, truncation, degradation, and compatibility shaping are testable as behavior.
17. As a developer, I want startup validation for embedding dimensionality, so that an incompatible configured embedding model fails fast before query traffic.
18. As a developer, I want the embedding provider to use the same configured text-embedding model boundary as ingestion, so that stored document vectors and query vectors are compatible.
19. As a developer, I want confidence thresholds documented against cosine similarity, so that future changes do not invert distance and similarity semantics.
20. As a developer, I want the tool to avoid Gemini and the model router entirely, so that retrieval does not add token cost, latency, or nondeterministic reranking.
21. As a developer, I want `allow_external` accepted but ignored for external search, so that this tool remains internally bounded even when callers pass the flag.
22. As a developer, I want telemetry to explicitly show external search was not used, so that future operators do not misread retrieval cost or provenance.
23. As a developer, I want whitespace-safe and sentence-aware chunk truncation where cheap, so that compact chunks remain semantically useful.
24. As a developer, I want invalid input to return the standard MCP error envelope, so that caller mistakes are distinct from degraded retrieval infrastructure.
25. As a developer, I want missing configuration to return a degraded empty result, so that local and CI behavior stays predictable without paid services.
26. As a developer, I want embedding failures to return a degraded empty result with `failure_stage: embedding`, so that observability points to the correct boundary.
27. As a developer, I want RPC failures to return a degraded empty result with `failure_stage: rpc`, so that database failures are diagnosable.
28. As a developer, I want configuration failures to return a degraded empty result with `failure_stage: config`, so that startup and environment issues are diagnosable.
29. As an operator, I want retrieval latency logged compactly, so that the demo and interview workflow can show production-style observability.
30. As an operator, I want retrieval logs to avoid query embeddings, result embeddings, full documents, full prompts, and verbose traces, so that telemetry remains compact.
31. As a reviewer, I want tests to prove exact RPC parameter shape, so that metadata filters and top-k caps do not silently drift.
32. As a reviewer, I want tests to prove no Gemini or model-router invocation occurs, so that the low-cost architecture is enforceable.
33. As a future agent implementer, I want a stable retrieval contract, so that match analyst, fan gathering, city concierge, and itinerary agents can share the same evidence tool.

## Implementation Decisions

- `search_documents` will become the primary RAG retrieval tool for ADK agents through MCP.
- Tool access remains through MCP. Agents must not bypass the MCP boundary to query Supabase or embeddings directly.
- The primary input contract will be `query`, optional nullable `city_id`, optional nullable `team_id`, optional nullable `category`, and `top_k` defaulting to 5.
- `top_k` will be validated and capped at 8.
- Backward compatibility may accept the previous `filters` and `limit` shape, but the canonical public contract for this feature is the explicit field shape.
- Metadata filters will be exact-match only.
- `category` maps directly to the stored document category metadata.
- The tool will call the Supabase pgvector RPC that returns document chunk matches and source metadata.
- Query embedding will be generated inside the retrieval boundary using the configured internal text-embedding provider.
- The query embedding provider will not call Gemini and will not use the model router.
- The embedding model used for query embeddings must be compatible with stored document embeddings.
- Embedding dimensionality must be validated at application startup against the expected vector dimension of 768. An incompatible configured model should fail fast before serving retrieval traffic.
- The retrieval architecture will use three clear boundaries: an embedding provider, a vector search repository, and a retrieval service.
- The embedding provider owns query embedding generation and dimensionality validation.
- The vector search repository owns calling the Supabase RPC and preserving exact RPC parameter shape.
- The retrieval service owns orchestration, input normalization, top-k bounding, confidence calculation, chunk compaction, degraded envelopes, and compatibility output shaping.
- The RPC returns cosine similarity as `1 - cosine_distance` from pgvector cosine distance semantics. Confidence thresholds must be interpreted as higher-is-better similarity.
- Retrieval confidence will be deterministic and based on similarity scores only.
- Empty successful RPC results will return `retrieval_confidence: none`, `ok: true`, and non-degraded telemetry.
- Infrastructure or configuration failures will return `ok: true` with an empty degraded result rather than raising unhandled exceptions to agents.
- Degraded responses will include telemetry with `failure_stage` values such as `config`, `embedding`, or `rpc`.
- The tool will preserve existing `data.results[]` compatibility as a derived shape from canonical retrieval data.
- Canonical retrieval data will include `chunks`, `source_paths`, `similarity_scores`, `document_titles`, `retrieval_confidence`, and degraded state.
- Returned chunk text will be deterministically compacted and must not return massive documents.
- Chunk compaction should prefer sentence-boundary truncation when cheap, then whitespace-safe truncation, instead of naive fixed substring cuts.
- Retrieval logging will rely on the Supabase RPC's compact retrieval log behavior and the existing MCP telemetry/trace pipeline.
- Retrieval logs and telemetry must not store query embeddings, result embeddings, full documents, full prompts, or verbose traces.
- `allow_external` will remain accepted from the shared tool input model but will not trigger external web search.
- Telemetry will explicitly report that external search was not used.
- The tool will not implement lexical fallback in this ticket.
- The tool will not implement LLM reranking in this ticket.
- The tool will not call Gemini, Gemini Pro, expensive reasoning models, or any model-based ranking path.

## Testing Decisions

- Tests should assert external behavior and stable contracts rather than private implementation details.
- Handler or service tests should use fake embedding providers and fake vector repositories so no test requires Supabase, Vertex AI, Google Cloud credentials, Gemini, or network access.
- Tests should verify default `top_k` is 5 and maximum `top_k` is 8.
- Tests should verify invalid `top_k` values return the standard MCP invalid-input behavior.
- Tests should verify `city_id`, `team_id`, and `category` filters are propagated exactly to the vector RPC boundary.
- Tests should verify exact RPC parameter shape, including query embedding, match count, filters, and query text.
- Tests should verify the tool returns canonical fields: chunks, source paths, similarity scores, document titles, retrieval confidence, degraded state, and telemetry.
- Tests should verify `data.results[]` is derived from canonical retrieval data for compatibility.
- Tests should verify successful empty retrievals are non-degraded and return `retrieval_confidence: none`.
- Tests should verify infrastructure failures return degraded empty retrievals with telemetry.
- Tests should verify failure stages are reported for configuration, embedding, and RPC failures.
- Tests should verify confidence calculation for high, medium, low, and none cases using cosine similarity semantics.
- Tests should verify chunk truncation is bounded and preserves useful text boundaries where practical.
- Tests should verify `allow_external` does not invoke external search and telemetry reports `external_search_used: false`.
- Tests should verify no Gemini or model-router invocation occurs during retrieval.
- Existing MCP registry, schema, middleware, trace, and tool-call tests should continue to pass.
- Test priority should focus first on degraded infrastructure paths, filter propagation correctness, confidence calculation, top-k cap enforcement, no Gemini/model-router invocation, and exact RPC parameter shape.

## Out of Scope

- LLM reranking.
- Gemini calls inside retrieval.
- Gemini Pro or expensive reasoning model usage.
- Lexical fallback.
- External web search.
- Agent-side ranking, filtering, hotspot scoring, itinerary ordering, or deterministic retrieval logic.
- Reworking the ingestion pipeline.
- Re-embedding the corpus.
- Changing the Supabase vector schema beyond what is required for compatibility with the existing RPC contract.
- Adding hosted observability dashboards or paid tracing sinks.
- Returning full documents or massive chunks.
- Storing query embeddings, result embeddings, full prompts, full completions, or full documents in logs.
- Building new ADK agent synthesis behavior on top of retrieved chunks.

## Further Notes

- The current Supabase RPC contract expects 768-dimensional vectors. Query embedding configuration must remain aligned with this schema.
- The current corpus is intentionally compact and curated, so vector retrieval without reranking is the right cost and reliability tradeoff for this ticket.
- Confidence thresholds should be treated as product/engineering defaults, not a claim of statistical calibration. They can be tuned later with evals.
- The compatibility `results` shape exists to avoid breaking older MCP consumers, but new agents should prefer canonical retrieval fields.
- The strongest implementation risks are mixing provider, repository, and orchestration concerns into the MCP handler; accidentally introducing Gemini/model-router calls; and allowing old `limit <= 20` behavior to bypass the new `top_k <= 8` cap.
- This feature should be demo-friendly: deterministic inputs, bounded outputs, compact telemetry, and clear degraded behavior are more valuable than broad recall.
