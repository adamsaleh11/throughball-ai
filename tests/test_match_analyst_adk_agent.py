"""Tests for the ADK-backed MatchAnalystAgent (03-06).

Stub model: _StubLlm subclasses BaseLlm — no live API calls in any non-smoke test.
MCP layer: injected via mcp_factory=lambda: _MockMCP() — preserves the tool boundary.
Flash-only: there is no Pro model path to exercise.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import AsyncGenerator

import pytest
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai.types import Content, FunctionCall, Part

from throughball_ai.agents.match_analyst_adk import MatchAnalystADKAgent
from throughball_ai.config import Settings


# ---------------------------------------------------------------------------
# Shared mock MCP — contract-shaped seeded responses
# ---------------------------------------------------------------------------

_MATCH_STATE_SEEDED = {
    "ok": True,
    "tool": "get_match_state",
    "source_type": "seeded",
    "data": {
        "match_id": "match_123",
        "home_team_id": "team_home",
        "away_team_id": "team_away",
        "status": "live",
        "minute": 67,
        "score": {"home": 2, "away": 1},
        "timeline": [
            {"minute": 64, "event_type": "goal", "team_id": "team_home"},
        ],
    },
}

_TEAM_PROFILE_SEEDED = {
    "ok": True,
    "tool": "get_team_profile",
    "source_type": "seeded",
    "data": {
        "team_id": "team_home",
        "name": "Home National Team",
        "supporter_notes": ["Defends leads well."],
        "evidence_ids": ["doc_123"],
    },
}

_SEARCH_RESULTS = {
    "ok": True,
    "tool": "search_documents",
    "source_type": "internal",
    "data": {
        "chunks": ["Home team historically protects 2-1 leads.", "Late goals are rare."],
        "source_paths": ["knowledge/home_team_history.md", "knowledge/late_goals.md"],
        "document_titles": ["Home Team History", "Late Goals Study"],
        "results": [
            {"document_id": "doc_123", "title": "Home Team History", "snippet": "Protects leads."},
            {"document_id": "doc_456", "title": "Late Goals Study", "snippet": "Rare."},
        ],
        "degraded": False,
    },
    "telemetry": {"degraded": False, "external_api_called": False},
}


class _ToolResult:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)


class _MockMCP:
    """Returns seeded contract-shaped responses for all three tools.

    Records each call so tests can assert dedupe / budget behavior.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        mapping = {
            "get_match_state": _MATCH_STATE_SEEDED,
            "get_team_profile": _TEAM_PROFILE_SEEDED,
            "search_documents": _SEARCH_RESULTS,
        }
        return [_ToolResult(mapping[name])]


_SEARCH_RESULTS_8 = {
    "ok": True,
    "tool": "search_documents",
    "source_type": "internal",
    "data": {
        "chunks": [f"chunk {i}" for i in range(8)],
        "source_paths": [f"knowledge/doc_{i}.md" for i in range(8)],
        "document_titles": [f"Doc {i}" for i in range(8)],
        "results": [{"document_id": f"doc_{i}", "title": f"Doc {i}", "snippet": f"s{i}"} for i in range(8)],
        "degraded": False,
    },
    "telemetry": {"degraded": False, "external_api_called": False},
}


class _MockMCPManyChunks(_MockMCP):
    """search_documents returns 8 chunks — agent must truncate to 5."""

    async def call_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        if name == "search_documents":
            return [_ToolResult(_SEARCH_RESULTS_8)]
        mapping = {"get_match_state": _MATCH_STATE_SEEDED, "get_team_profile": _TEAM_PROFILE_SEEDED}
        return [_ToolResult(mapping[name])]


class _MockMCPSearchError(_MockMCP):
    """search_documents raises; other tools return seeded data."""

    async def call_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        if name == "search_documents":
            raise TimeoutError("retrieval unavailable")
        mapping = {"get_match_state": _MATCH_STATE_SEEDED, "get_team_profile": _TEAM_PROFILE_SEEDED}
        return [_ToolResult(mapping[name])]


# ---------------------------------------------------------------------------
# Stub LLM scenarios
# ---------------------------------------------------------------------------


class Scenario(str, Enum):
    MATCH_ONLY = "match_only"   # one tool call (get_match_state) → final text
    FULL = "full"              # three tool calls → final text with facts/inferences/citations
    DUP_SEARCH = "dup_search"  # match_state + search_documents twice (same query)
    EXCEED = "exceed"          # five tool calls attempted → budget blocks the 5th
    BAD_CITE = "bad_cite"      # match_state + search, but answer cites unresolved [9]
    NO_MATCH = "no_match"      # only search_documents, yet answer claims score/momentum
    HISTORICAL = "historical"  # match_state + search, grounded answer, no momentum claim


_FINAL_TEXT = (
    "Fact: The home team leads 2-1 at minute 67. "
    "Fact: The home team scored at minute 64. "
    "Inferred: The home team has momentum after the recent goal. "
    "Historical context: this team protects 2-1 leads well [1]."
)

_FINAL_TEXT_BY_SCENARIO = {
    Scenario.BAD_CITE: (
        "Fact: The home team leads 2-1 at minute 67. "
        "Inferred: The home team has momentum. "
        "This is supported by historical record [9]."
    ),
    Scenario.NO_MATCH: (
        "Fact: The home team leads 2-1 at minute 67. "
        "Inferred: The home team has momentum after a late goal."
    ),
    Scenario.HISTORICAL: (
        "Fact: The home team leads 2-1 at minute 67. "
        "Inferred: This team is tactically disciplined when defending a lead [1]."
    ),
}


class _StubLlm(BaseLlm):
    """Canned LLM that never calls a live model."""

    model_name: str = "stub-gemini-flash"
    scenario: str = Scenario.MATCH_ONLY

    @classmethod
    def supported_models(cls):
        return ["stub-gemini-flash"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        has_fn_resp = any(
            p.function_response is not None
            for c in (llm_request.contents or [])
            for p in (c.parts or [])
        )

        if has_fn_resp:
            final_text = _FINAL_TEXT_BY_SCENARIO.get(self.scenario, _FINAL_TEXT)
            yield LlmResponse(
                content=Content(role="model", parts=[Part(text=final_text)]),
                usage_metadata=_usage(),
                model_version="gemini-2.0-flash-001",
                turn_complete=True,
            )
            return

        if self.scenario == Scenario.MATCH_ONLY:
            calls = [
                Part(function_call=FunctionCall(
                    name="get_match_state",
                    args={"match_id": "match_123", "include_timeline": True},
                )),
            ]
        elif self.scenario == Scenario.DUP_SEARCH:
            calls = [
                Part(function_call=FunctionCall(
                    name="get_match_state", args={"match_id": "match_123", "include_timeline": True},
                )),
                Part(function_call=FunctionCall(
                    name="search_documents", args={"query": "home team history", "top_k": 5},
                )),
                Part(function_call=FunctionCall(
                    name="search_documents", args={"query": "home team history", "top_k": 5},
                )),
            ]
        elif self.scenario == Scenario.EXCEED:
            calls = [
                Part(function_call=FunctionCall(name="get_match_state", args={"match_id": "m", "include_timeline": True})),
                Part(function_call=FunctionCall(name="get_team_profile", args={"team_id": "team_home", "include_evidence": True})),
                Part(function_call=FunctionCall(name="search_documents", args={"query": "q1", "top_k": 5})),
                Part(function_call=FunctionCall(name="search_documents", args={"query": "q2", "top_k": 5})),
                Part(function_call=FunctionCall(name="get_team_profile", args={"team_id": "team_away", "include_evidence": True})),
            ]
        elif self.scenario == Scenario.NO_MATCH:
            calls = [
                Part(function_call=FunctionCall(
                    name="search_documents", args={"query": "home team momentum", "top_k": 5},
                )),
            ]
        elif self.scenario in (Scenario.BAD_CITE, Scenario.HISTORICAL):
            calls = [
                Part(function_call=FunctionCall(
                    name="get_match_state", args={"match_id": "match_123", "include_timeline": True},
                )),
                Part(function_call=FunctionCall(
                    name="search_documents", args={"query": "home team history", "top_k": 5},
                )),
            ]
        else:  # FULL
            calls = [
                Part(function_call=FunctionCall(
                    name="get_match_state",
                    args={"match_id": "match_123", "include_timeline": True},
                )),
                Part(function_call=FunctionCall(
                    name="get_team_profile",
                    args={"team_id": "team_home", "include_evidence": True},
                )),
                Part(function_call=FunctionCall(
                    name="search_documents",
                    args={"query": "home team protects leads", "top_k": 5},
                )),
            ]

        yield LlmResponse(
            content=Content(role="model", parts=calls),
            usage_metadata=_usage(),
            model_version="gemini-2.0-flash-001",
            turn_complete=False,
        )


class _UsageMeta:
    """Mimics google.genai usage_metadata with the attributes the agent reads."""

    prompt_token_count = 120
    candidates_token_count = 80
    total_token_count = 200


def _usage() -> _UsageMeta:
    return _UsageMeta()


def _make_agent(scenario: Scenario = Scenario.MATCH_ONLY, mcp_factory=None) -> MatchAnalystADKAgent:
    stub = _StubLlm(model="stub-gemini-flash", scenario=scenario)
    settings = Settings(GEMINI_FLASH_MODEL="stub-gemini-flash")
    return MatchAnalystADKAgent(
        stub_model=stub,
        mcp_factory=mcp_factory or (lambda: _MockMCP()),
        settings=settings,
    )


# ===========================================================================
# Phase 1 — Flash-only skeleton + real metrics
# ===========================================================================


@pytest.mark.asyncio
async def test_agent_returns_answer_with_flash_model_name():
    agent = _make_agent(Scenario.MATCH_ONLY)
    response = await agent.answer(
        query="What's the score and momentum?",
        session_id="sess_1",
        match_id="match_123",
    )
    assert response["answer"]
    assert "flash" in response["model_name"]
    assert "pro" not in response["model_name"].lower()


@pytest.mark.asyncio
async def test_metrics_have_real_cost_and_tokens_per_second():
    agent = _make_agent(Scenario.MATCH_ONLY)
    response = await agent.answer(
        query="What's the score?", session_id="sess_1", match_id="match_123"
    )
    metrics = response["metrics"]
    # Real values derived from usage_metadata, not placeholders.
    assert metrics["cost_per_request"] > 0
    assert metrics["tokens_per_second"] > 0
    assert metrics["completion_tokens"] == 80
    assert metrics["prompt_tokens"] == 120


@pytest.mark.asyncio
async def test_simple_query_uses_only_match_state():
    mcp = _MockMCP()
    agent = _make_agent(Scenario.MATCH_ONLY, mcp_factory=lambda: mcp)
    response = await agent.answer(
        query="What's the score?", session_id="sess_1", match_id="match_123"
    )
    tool_names = {s["tool"] for s in response["tool_sources"]}
    assert tool_names == {"get_match_state"}
    assert response["metrics"]["tool_call_count"] == 1


# ===========================================================================
# Phase 2 — Full toolset + cost rules
# ===========================================================================


@pytest.mark.asyncio
async def test_full_query_uses_all_three_tools():
    mcp = _MockMCP()
    agent = _make_agent(Scenario.FULL, mcp_factory=lambda: mcp)
    response = await agent.answer(
        query="How does this team handle a 2-1 lead historically?",
        session_id="sess_1",
        match_id="match_123",
    )
    tool_names = {s["tool"] for s in response["tool_sources"]}
    assert tool_names == {"get_match_state", "get_team_profile", "search_documents"}


@pytest.mark.asyncio
async def test_retrieved_chunks_capped_at_five():
    mcp = _MockMCPManyChunks()
    agent = _make_agent(Scenario.FULL, mcp_factory=lambda: mcp)
    await agent.answer(
        query="History?", session_id="sess_1", match_id="match_123"
    )
    # The wrapper passes top_k=5 to the tool regardless of the model's requested top_k.
    search_call = next(a for (n, a) in mcp.calls if n == "search_documents")
    assert search_call["top_k"] == 5


@pytest.mark.asyncio
async def test_chunks_truncated_to_five_in_citations():
    mcp = _MockMCPManyChunks()
    agent = _make_agent(Scenario.FULL, mcp_factory=lambda: mcp)
    response = await agent.answer(
        query="History?", session_id="sess_1", match_id="match_123"
    )
    numbered = [c for c in response["citations"] if c["id"] is not None]
    assert all(c["id"] <= 5 for c in numbered)


@pytest.mark.asyncio
async def test_duplicate_search_query_is_deduped():
    mcp = _MockMCP()
    agent = _make_agent(Scenario.DUP_SEARCH, mcp_factory=lambda: mcp)
    await agent.answer(query="History?", session_id="sess_1", match_id="match_123")
    search_calls = [c for c in mcp.calls if c[0] == "search_documents"]
    assert len(search_calls) == 1  # second identical query served from cache


@pytest.mark.asyncio
async def test_tool_call_budget_capped_at_four():
    mcp = _MockMCP()
    agent = _make_agent(Scenario.EXCEED, mcp_factory=lambda: mcp)
    response = await agent.answer(query="Analyze.", session_id="sess_1", match_id="match_123")
    assert response["answer"] is not None
    assert response["metrics"]["tool_call_count"] <= 4


@pytest.mark.asyncio
async def test_search_tool_error_degrades_gracefully():
    mcp = _MockMCPSearchError()
    agent = _make_agent(Scenario.FULL, mcp_factory=lambda: mcp)
    response = await agent.answer(query="History?", session_id="sess_1", match_id="match_123")
    assert response["answer"]  # run still completes
    assert response["degraded"] is True
    search_source = next((s for s in response["tool_sources"] if s["tool"] == "search_documents"), None)
    assert search_source is not None and search_source["degraded"] is True


# ===========================================================================
# Phase 3 — Facts vs inference + citations
# ===========================================================================


@pytest.mark.asyncio
async def test_facts_and_inferences_are_separated():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(
        query="Analyze the lead.", session_id="sess_1", match_id="match_123"
    )
    assert response["facts"], "expected at least one fact"
    assert response["inferences"], "expected at least one inference"
    # Facts are grounded values; inferences are interpretation. No overlap.
    fact_claims = {f["claim"] for f in response["facts"]}
    inf_claims = {i["claim"] for i in response["inferences"]}
    assert fact_claims.isdisjoint(inf_claims)
    assert any("momentum" in i["claim"].lower() for i in response["inferences"])


@pytest.mark.asyncio
async def test_fact_about_score_is_sourced_to_match_state():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(
        query="Score?", session_id="sess_1", match_id="match_123"
    )
    score_fact = next((f for f in response["facts"] if "2-1" in f["claim"]), None)
    assert score_fact is not None
    assert score_fact["source"] == "get_match_state"


@pytest.mark.asyncio
async def test_citations_map_to_real_retrieved_documents():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(
        query="History?", session_id="sess_1", match_id="match_123"
    )
    numbered = [c for c in response["citations"] if c["id"] is not None]
    assert numbered, "expected a numbered document citation"
    cite = numbered[0]
    # Maps to the real first search result, not a fabricated source_N.
    assert cite["title"] == "Home Team History"
    assert cite["source_path"] in ("knowledge/home_team_history.md", "doc_123")


@pytest.mark.asyncio
async def test_team_evidence_ids_become_citations():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(
        query="History?", session_id="sess_1", match_id="match_123"
    )
    evidence = [c for c in response["citations"] if c["source_path"] == "doc_123" and c["id"] is None]
    assert evidence, "team_profile evidence_ids should appear as citations"


# ===========================================================================
# Phase 4 — Self-check, confidence & degradation
# ===========================================================================


@pytest.mark.asyncio
async def test_unsupported_citation_sets_degraded():
    agent = _make_agent(Scenario.BAD_CITE)
    response = await agent.answer(query="Analyze.", session_id="sess_1", match_id="match_123")
    assert response["self_check"]["passed"] is False
    assert response["degraded"] is True
    assert "citation" in response["degraded_reason"].lower()


@pytest.mark.asyncio
async def test_momentum_claim_without_match_state_is_flagged():
    agent = _make_agent(Scenario.NO_MATCH)
    response = await agent.answer(query="Momentum?", session_id="sess_1", match_id="match_123")
    assert response["self_check"]["passed"] is False
    assert response["degraded"] is True
    assert response["confidence"] == "low"


@pytest.mark.asyncio
async def test_self_check_passes_on_grounded_answer():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(query="Analyze.", session_id="sess_1", match_id="match_123")
    assert response["self_check"]["passed"] is True
    assert response["degraded"] is False


@pytest.mark.asyncio
async def test_self_check_failure_does_not_trigger_reprompt_loop():
    mcp = _MockMCP()
    agent = _make_agent(Scenario.BAD_CITE, mcp_factory=lambda: mcp)
    await agent.answer(query="Analyze.", session_id="sess_1", match_id="match_123")
    # Exactly the two tool calls the model issued — no extra retrieval after the failed check.
    assert len(mcp.calls) == 2


@pytest.mark.asyncio
async def test_confidence_high_when_grounded_without_momentum_claim():
    agent = _make_agent(Scenario.HISTORICAL)
    response = await agent.answer(query="History?", session_id="sess_1", match_id="match_123")
    assert response["confidence"] == "high"


@pytest.mark.asyncio
async def test_seeded_momentum_claim_caps_confidence_at_medium():
    agent = _make_agent(Scenario.FULL)
    response = await agent.answer(query="Momentum?", session_id="sess_1", match_id="match_123")
    assert response["confidence"] == "medium"
    assert any("seeded" in r.lower() for r in response["confidence_details"]["downgrade_reasons"])


@pytest.mark.asyncio
async def test_confidence_low_when_a_tool_is_degraded():
    mcp = _MockMCPSearchError()
    agent = _make_agent(Scenario.FULL, mcp_factory=lambda: mcp)
    response = await agent.answer(query="History?", session_id="sess_1", match_id="match_123")
    assert response["confidence"] == "low"
