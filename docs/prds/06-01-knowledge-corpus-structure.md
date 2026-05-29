# PRD: Knowledge Corpus Structure

## Problem Statement

WorldPulse needs a curated markdown knowledge corpus to power RAG-backed supporter intelligence for the 2026 tournament experience. The repo already contains a broad 16-city seed corpus, but the structure is incomplete for the required category set, the current category documents are highly repetitive, and the acceptance criteria need to be reconciled with the product decision to keep all 16 host cities polished rather than shrinking to a 20-50 file pilot.

This matters because the corpus is the grounding layer for AI agents that explain cities, venues, supporter hotspots, transportation, tourism, safety, and matchday context. If the source documents are too repetitive, too vague, or missing required categories, retrieval quality declines and the AI layer is more likely to produce generic or unsupported answers. The corpus must stay intentionally curated and cheap to embed while still giving every city enough distinct, human-readable source knowledge to support credible RAG behavior.

## Solution

Create and polish a source-only markdown corpus under the knowledge seed document tree. Preserve the existing 16-city coverage and organize documents by the required categories: cities, venues, fan-hotspots, transportation, match-previews, tourism, and safety. Add the missing match-previews category with one host-city matchday preview document per city or region.

Every city should be polished across every category. Category documents should carry distinct retrieval value instead of repeating the same generic text. Each document should remain small, human-readable, and optimized for cheap embedding. Every document should include clear source or confidence notes that distinguish official facts, curated summaries, inferred supporter behavior, and community-informed signals where relevant.

The corpus must remain source knowledge only. The implementation must not commit generated embeddings, chunk outputs, vector indexes, database exports, or massive scraped web content.

## User Stories

1. As a WorldPulse user, I want city overview knowledge for every supported host city, so that city-level answers are grounded in curated local context.
2. As a WorldPulse user, I want venue knowledge for every supported host city, so that stadium and matchday location answers are grounded in venue-specific facts.
3. As a WorldPulse user, I want fan-hotspot knowledge for every supported host city, so that supporter gathering answers have city-specific context.
4. As a WorldPulse user, I want transportation knowledge for every supported host city, so that travel advice can account for local transit and congestion patterns.
5. As a WorldPulse user, I want match-preview knowledge for every supported host city, so that matchday explanations can include host-city context without inventing future fixture details.
6. As a WorldPulse user, I want tourism knowledge for every supported host city, so that football travel answers can connect matches with nearby visitor activities.
7. As a WorldPulse user, I want safety knowledge for every supported host city, so that recommendations can include practical caution without overstating risk.
8. As a fan, I want documents to distinguish verified signals from inferred or community-informed signals, so that I can judge how much confidence to place in the answer.
9. As a fan, I want match-preview content to avoid fake team or fixture claims, so that I am not misled by unconfirmed future details.
10. As a developer, I want the corpus organized by stable category folders, so that ingestion can load and filter source knowledge predictably.
11. As a developer, I want one polished document per city per required category, so that the 16-city corpus is symmetrical and easy to audit.
12. As a developer, I want each markdown file to be concise, so that embedding stays cheap and retrieval chunks remain focused.
13. As a developer, I want category documents to be meaningfully distinct, so that the same content is not embedded repeatedly under different names.
14. As a developer, I want realistic source and confidence notes in every document, so that downstream agents can cite grounding quality accurately.
15. As a developer, I want no generated vector, embedding, or chunk files committed, so that the repo remains source-controlled knowledge rather than generated retrieval output.
16. As a developer, I want the corpus to avoid massive scraped webpages, so that source files stay curated, reviewable, and cheap to maintain.
17. As a reviewer, I want acceptance checks that verify category coverage and forbidden artifact absence, so that the ticket can be validated without reading every document manually.
18. As a reviewer, I want the PRD to explicitly explain why the corpus exceeds the original 20-50 file target, so that the 16-city decision is not mistaken for accidental scope creep.
19. As an operator, I want confidence levels to vary by evidence type, so that official venue or transit facts can be treated differently from inferred crowd behavior.
20. As an operator, I want every city polished rather than only Toronto and Vancouver, so that the demo experience does not degrade outside the first two Canadian cities.

## Implementation Decisions

- The corpus will keep the existing 16-city and region coverage: Atlanta, Boston, Dallas, Guadalajara, Houston, Kansas City, Los Angeles, Mexico City, Miami, Monterrey, New York/New Jersey, Philadelphia, San Francisco Bay Area, Seattle, Toronto, and Vancouver.
- Every supported city or region will have one polished source document in each required category.
- The required categories are cities, venues, fan-hotspots, transportation, match-previews, tourism, and safety.
- The missing match-previews category will be added as host-city matchday preview context, not fixture-specific team previews.
- Match-preview documents will avoid claims about unconfirmed matchups, team form, or live fixture state unless those facts are explicitly represented in curated source notes.
- The implementation intentionally exceeds the original 20-50 document target because the accepted product decision is full 16-city coverage across all required categories.
- The cost-control interpretation for this ticket is small, curated documents and no repeated embeddings of generic content, rather than reducing city coverage.
- Each document should remain compact enough for cheap embedding, with a target range of roughly 200-500 words unless a specific city requires a modest exception.
- Existing simple markdown metadata may be preserved. A schema migration to YAML frontmatter is not required unless a future ingestion task establishes that contract.
- Each file will include source or confidence notes. Notes should make clear whether content is based on official venue/transit/tourism facts, curated editorial summary, community-informed signals, or inferred matchday behavior.
- Confidence should not be uniformly set to one level when the evidence type differs. Official infrastructure and venue facts can be high confidence; supporter behavior and inferred hotspots should generally be medium or lower unless strongly supported.
- Category documents should be rewritten or adjusted enough to provide category-specific retrieval value and reduce repeated boilerplate across categories.
- The corpus remains source knowledge only. Generated embeddings, vector indexes, chunk output, JSONL chunk exports, FAISS files, SQLite retrieval databases, and similar artifacts are not part of this work.
- The work should not add scraping pipelines or large raw webpage captures. Curated summaries are preferred over raw source dumps.
- No new external model usage is required to complete this ticket.
- No application API, MCP tool, database schema, or runtime behavior change is required for the corpus-structure ticket unless a lightweight validation check is added.

## Testing Decisions

- Tests and checks should verify external corpus behavior and acceptance criteria rather than the exact prose of each document.
- Coverage checks should verify that every required category folder exists.
- Coverage checks should verify that every supported city or region has one markdown document per required category.
- Artifact checks should verify that generated embedding, vector, chunk, database, and index files are absent from the knowledge corpus.
- Content checks should verify that markdown files include confidence or source notes.
- Content checks should verify that match-preview files exist and do not rely on fixture-specific claims as their core structure.
- Review should sample documents across all categories, not just Toronto and Vancouver, because every city is expected to be polished.
- Existing tests should continue to pass. If an automated corpus validation command exists or is added, it should run without external network access.

## Out of Scope

- Generating embeddings.
- Committing vector stores, chunk outputs, retrieval database files, or embedding artifacts.
- Building ingestion, chunking, or retrieval pipelines.
- Adding Supabase, pgvector, FAISS, or other vector infrastructure.
- Scraping large raw webpages into the repo.
- Live event data, real-time crowd detection, or live transit disruption feeds.
- Fixture-specific tactical match previews, team form analysis, or confirmed match schedules beyond curated host-city matchday context.
- Building or modifying AI agents, MCP tools, API routes, or frontend user experiences.
- Reducing the corpus to 20-50 files.

## Further Notes

- The 20-50 file requirement in the original ticket conflicts with the confirmed decision to keep the current 16-city corpus. The implementation should treat the 16-city decision as authoritative and document that the corpus will be larger because it provides seven categories for every city.
- The most important quality risk is repetitive category text. A reviewer should be able to open documents from the same city across different categories and see distinct retrieval value.
- Toronto and Vancouver should remain strong examples, but every city should be polished to the same standard.
- The corpus should support the repo principle that AI explains and synthesizes while deterministic ranking, filtering, hotspot scoring, and itinerary ordering remain backend responsibilities.
- Future ingestion work can use this corpus as source input, but this ticket should stop before generated retrieval artifacts are produced.
