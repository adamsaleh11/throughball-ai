# AGENTS.md — throughball-ai

# PURPOSE

This repo owns:
- orchestration
- MCP
- Gemini Flash integration
- AI reasoning synthesis
- evals
- retries
- confidence systems
- telemetry

This repo is intentionally:
LOW-COST and ORCHESTRATION-FIRST.

The system demonstrates:
AI systems engineering,
NOT expensive model usage.

---

# MODEL STRATEGY

Primary model:
Gemini Flash ONLY.

Avoid:
- Gemini Pro
- expensive reasoning models
- giant contexts

The architecture is model-agnostic.

---

# IMPORTANT ENGINEERING PRINCIPLE

AI should:
- explain
- synthesize
- orchestrate
- route
- summarize

AI should NOT:
- perform deterministic ranking
- perform filtering
- calculate hotspot scores
- calculate itinerary ordering

Those belong in the backend.

---

# AGENT RESPONSIBILITIES

## Orchestrator Agent
Handles:
- routing
- delegation
- retries
- synthesis

---

## Match Analyst Agent
Explains:
- tactical momentum
- player insights
- historical context

Must use:
retrieved evidence.

---

## Fan Gathering Agent
Explains:
- supporter hotspots
- crowd activity
- confidence

Must distinguish:
verified vs inferred signals.

---

## City Concierge Agent
Explains:
- nightlife
- tourism
- recommendations

Backend computes ranking candidates first.

---

## Itinerary Agent
Formats:
- multi-day itineraries
- schedules
- explanations

Backend computes sequencing first.

---

# COST RULES

Minimize:
- prompt size
- token usage
- repeated retrieval
- unnecessary eval loops

Use:
- cached retrievals
- short contexts
- deterministic preprocessing

---

# MCP RULES

ALL tool access goes through MCP.

Every tool emits:
- traces
- latency
- retries
- degraded state

---

# OBSERVABILITY RULES

Store:
- summaries
- metrics
- IDs

Avoid:
- giant verbose logs
- full prompt dumps
- excessive traces

---

# ARCHITECTURE PHILOSOPHY

This repo demonstrates:
production AI orchestration
with strong engineering discipline
and minimal operational cost.
