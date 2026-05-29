# Plan: Knowledge Corpus Structure

> Source PRD: `docs/prds/06-01-knowledge-corpus-structure.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no new HTTP route is required for this slice; the stable public surface is the committed markdown corpus under the knowledge seed document tree.
- **Schema**: source documents remain human-readable markdown with a lightweight metadata section, category content, and source or confidence notes.
- **Key models**: supported host city or region, required knowledge category, source knowledge document, confidence/source note.
- **Auth**: no authentication or authorization changes.
- **External services**: no external service integration is required; this slice does not generate embeddings or call model APIs.
- **Corpus scope**: preserve the 16-city corpus and provide every required category for every city.
- **Cost controls**: keep documents concise, category-specific, source-only, and free of generated vector or chunk artifacts.

---

## Phase 1: Add Required Category Coverage

**User stories**: 5, 10, 11, 17

### What to build

Add the missing match-preview source category so the corpus is structurally complete across all 16 supported cities and regions. Match-preview documents describe host-city matchday context rather than unconfirmed fixture-specific team previews.

### Acceptance criteria

- [ ] The match-preview category exists in the knowledge seed document tree.
- [ ] Every supported city or region has one match-preview markdown document.
- [ ] Match-preview documents avoid fake team matchups, live fixture claims, and unsupported team-form analysis.
- [ ] The corpus has one markdown source document per city per required category.

---

## Phase 2: Polish Category-Specific Retrieval Value

**User stories**: 1-7, 12, 13, 20

### What to build

Revise the existing source documents so every city is polished and each category contributes distinct retrieval value. City overview, venue, hotspot, transportation, tourism, safety, and match-preview documents should answer different retrieval needs instead of repeating one generic city summary.

### Acceptance criteria

- [ ] Every supported city has category-specific content across all required categories.
- [ ] Documents remain concise enough for cheap embedding.
- [ ] Boilerplate repetition is reduced so categories do not embed the same content repeatedly.
- [ ] Toronto and Vancouver remain strong examples, and the remaining cities are polished to the same standard.

---

## Phase 3: Normalize Source and Confidence Notes

**User stories**: 8, 14, 19

### What to build

Ensure every source document includes realistic source and confidence notes. Notes should distinguish official venue, transit, and tourism facts from curated summaries, inferred matchday behavior, and community-informed supporter signals.

### Acceptance criteria

- [ ] Every markdown source document includes confidence metadata or confidence notes.
- [ ] Every markdown source document includes source notes.
- [ ] Confidence levels vary when evidence types differ.
- [ ] Fan-hotspot and matchday behavior documents distinguish verified and inferred signals.

---

## Phase 4: Protect Source-Only Corpus Boundaries

**User stories**: 15, 16

### What to build

Keep the knowledge corpus limited to curated source markdown. Validate that generated embeddings, chunk output, vector indexes, database exports, and massive raw scraped pages are absent.

### Acceptance criteria

- [ ] No generated embedding files are present in the knowledge corpus.
- [ ] No vector index files are present in the knowledge corpus.
- [ ] No chunk output exports are present in the knowledge corpus.
- [ ] No raw scraped webpage dumps are present in the knowledge corpus.

---

## Phase 5: Add Corpus Acceptance Checks

**User stories**: 17, 18

### What to build

Add lightweight behavior-level validation for the corpus so future edits can check structural completeness and source-only boundaries without manually reading every file.

### Acceptance criteria

- [ ] Validation verifies all required category folders exist.
- [ ] Validation verifies every supported city has one markdown file per required category.
- [ ] Validation verifies every source file has source and confidence notes.
- [ ] Validation verifies forbidden generated artifacts are absent.
- [ ] Validation documents that the corpus intentionally exceeds the original 20-50 file target because 16-city coverage is the accepted scope.
