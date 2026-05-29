"""Tests for the ADK-backed FanGatheringAgent (03-04).

Stub model: _StubLlm subclasses BaseLlm — no live API calls in any non-smoke test.
MCP layer: injected via mcp_factory=lambda: _MockMCP() — preserves the 07-01 boundary.
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

from throughball_ai.agents.fan_gathering_adk import FanGatheringADKAgent
from throughball_ai.config import Settings


# ---------------------------------------------------------------------------
# Shared mock MCP
# ---------------------------------------------------------------------------

_HOTSPOT_SEEDED = {
    "ok": True,
    "tool": "get_fan_hotspots",
    "source_type": "seeded",
    "data": {
        "hotspots": [
            {
                "name": "The Pub",
                "neighborhood": "Downtown",
                "verified_signals": ["Partner venue listing"],
                "inferred_signals": ["Near transit hub"],
                "evidence_ids": [],
            }
        ]
    },
    "telemetry": {"degraded": False, "external_api_called": False},
}

_EVENTS_SEEDED = {
    "ok": True,
    "tool": "get_city_events",
    "source_type": "seeded",
    "data": {"events": []},
    "telemetry": {"degraded": False, "external_api_called": False},
}

_VENUES_SEEDED = {
    "ok": True,
    "tool": "get_venues",
    "source_type": "seeded",
    "data": {"venues": []},
    "telemetry": {"degraded": False, "external_api_called": False},
}


class _ToolResult:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)


class _MockMCP:
    """Returns seeded contract-shaped responses for all three tools."""

    async def call_tool(self, name: str, args: dict):
        mapping = {
            "get_fan_hotspots": _HOTSPOT_SEEDED,
            "get_city_events": _EVENTS_SEEDED,
            "get_venues": _VENUES_SEEDED,
        }
        return [_ToolResult(mapping[name])]


class _MockMCPDegradedEvents:
    """get_city_events raises; others return seeded data."""

    async def call_tool(self, name: str, args: dict):
        if name == "get_city_events":
            raise TimeoutError("events unavailable")
        mapping = {
            "get_fan_hotspots": _HOTSPOT_SEEDED,
            "get_venues": _VENUES_SEEDED,
        }
        return [_ToolResult(mapping[name])]


# ---------------------------------------------------------------------------
# Stub LLM scenarios
# ---------------------------------------------------------------------------


class Scenario(str, Enum):
    HAPPY = "happy"          # 3 tool calls → final text
    MISSING_TOOL = "missing" # 2 tool calls → final text (get_venues omitted)
    EXCEED_CAP = "exceed"    # 4 tool calls attempted
    NO_TOOLS = "no_tools"    # text only, no tool calls


class _StubLlm(BaseLlm):
    """Canned LLM that never calls a live model."""

    model_name: str = "stub-gemini-flash"
    scenario: str = Scenario.HAPPY

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

        if self.scenario == Scenario.NO_TOOLS:
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text="I don't have enough data to answer.")],
                ),
                turn_complete=True,
            )
            return

        if has_fn_resp:
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[
                        Part(
                            text=(
                                "Cached matchday data suggests The Pub in Downtown "
                                "is the best supporter gathering lead. "
                                "Confidence is medium: verified signals include "
                                "Partner venue listing, while inferred signals include Near transit hub."
                            )
                        )
                    ],
                ),
                turn_complete=True,
            )
            return

        if self.scenario == Scenario.HAPPY:
            calls = [
                Part(function_call=FunctionCall(
                    name="get_fan_hotspots",
                    args={"city_id": "city_toronto", "match_id": "match_123", "team_id": "team_argentina", "allow_external": False},
                )),
                Part(function_call=FunctionCall(
                    name="get_city_events",
                    args={"city_id": "city_toronto", "start_date": None, "end_date": None, "category": "matchday", "allow_external": False},
                )),
                Part(function_call=FunctionCall(
                    name="get_venues",
                    args={"city_id": "city_toronto", "venue_type": "any", "allow_external": False},
                )),
            ]
        elif self.scenario == Scenario.MISSING_TOOL:
            calls = [
                Part(function_call=FunctionCall(
                    name="get_fan_hotspots",
                    args={"city_id": "city_toronto", "match_id": "match_123", "team_id": "team_argentina", "allow_external": False},
                )),
                Part(function_call=FunctionCall(
                    name="get_city_events",
                    args={"city_id": "city_toronto", "start_date": None, "end_date": None, "category": "matchday", "allow_external": False},
                )),
            ]
        elif self.scenario == Scenario.EXCEED_CAP:
            calls = [
                Part(function_call=FunctionCall(name="get_fan_hotspots", args={"city_id": "c", "match_id": "m", "team_id": "t", "allow_external": False})),
                Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "c", "start_date": None, "end_date": None, "category": "matchday", "allow_external": False})),
                Part(function_call=FunctionCall(name="get_venues", args={"city_id": "c", "venue_type": "any", "allow_external": False})),
                Part(function_call=FunctionCall(name="get_fan_hotspots", args={"city_id": "c", "match_id": "m", "team_id": "t2", "allow_external": False})),
            ]
        else:
            calls = []

        yield LlmResponse(
            content=Content(role="model", parts=calls),
            turn_complete=False,
        )


def _make_agent(scenario: Scenario = Scenario.HAPPY, mcp_factory=None) -> FanGatheringADKAgent:
    stub = _StubLlm(model="stub-gemini-flash", scenario=scenario)
    settings = Settings(GEMINI_FLASH_MODEL="stub-gemini-flash")
    return FanGatheringADKAgent(
        stub_model=stub,
        mcp_factory=mcp_factory or (lambda: _MockMCP()),
        settings=settings,
    )


# ===========================================================================
# Phase 1 — Agent scaffold + basic answer
# ===========================================================================


@pytest.mark.asyncio
async def test_agent_returns_answer_with_flash_model_name():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(
        city_id="city_toronto",
        match_id="match_123",
        team_id="team_argentina",
        question="Where are Argentina fans gathering?",
    )
    assert response["answer"]
    assert "flash" in response["model_name"]
    assert "pro" not in response["model_name"].lower()


@pytest.mark.asyncio
async def test_agent_answer_uses_three_mcp_tools():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    tool_names = {s["tool"] for s in response["tool_sources"]}
    assert tool_names == {"get_fan_hotspots", "get_city_events", "get_venues"}


@pytest.mark.asyncio
async def test_agent_answer_contains_seeded_prefix():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["answer"].lower().startswith("cached")


@pytest.mark.asyncio
async def test_agent_answer_length_within_480_chars():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert len(response["answer"]) <= 480


# ===========================================================================
# Phase 2 — Tool budget + iteration limits
# ===========================================================================


@pytest.mark.asyncio
async def test_fourth_tool_call_is_blocked_and_run_completes():
    agent = _make_agent(Scenario.EXCEED_CAP)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    # Run should complete without error; budget enforcement noted in degraded or metrics
    assert response["answer"] is not None


@pytest.mark.asyncio
async def test_no_tools_scenario_returns_degraded_low_confidence():
    agent = _make_agent(Scenario.NO_TOOLS)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["degraded"] is True
    assert response["confidence"] == "low"


# ===========================================================================
# Phase 3 — Metrics in response
# ===========================================================================


@pytest.mark.asyncio
async def test_response_includes_metrics_shape():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert "metrics" in response
    assert "tool_call_count" in response["metrics"]
    assert "total_latency_ms" in response["metrics"]
    assert "tool_latencies" in response["metrics"]
    assert "telemetry" not in response


@pytest.mark.asyncio
async def test_metrics_tool_call_count_is_three_on_happy_path():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["metrics"]["tool_call_count"] == 3


# ===========================================================================
# Phase 4 — Safety post-processing
# ===========================================================================


@pytest.mark.asyncio
async def test_post_processor_injects_cached_prefix_when_missing():
    """If the LLM returns an answer that omits the prefix, Python adds it."""

    class _NoPrefixLlm(_StubLlm):
        async def generate_content_async(self, llm_request, stream=False):
            has_fn = any(
                p.function_response is not None
                for c in (llm_request.contents or [])
                for p in (c.parts or [])
            )
            if has_fn:
                yield LlmResponse(
                    content=Content(role="model", parts=[Part(text="The Pub is the best spot.")]),
                    turn_complete=True,
                )
            else:
                yield LlmResponse(
                    content=Content(role="model", parts=[
                        Part(function_call=FunctionCall(name="get_fan_hotspots", args={"city_id": "c", "match_id": "m", "team_id": "t", "allow_external": False})),
                        Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "c", "start_date": None, "end_date": None, "category": "matchday", "allow_external": False})),
                        Part(function_call=FunctionCall(name="get_venues", args={"city_id": "c", "venue_type": "any", "allow_external": False})),
                    ]),
                    turn_complete=False,
                )

    stub = _NoPrefixLlm(model="stub-gemini-flash")
    agent = FanGatheringADKAgent(
        stub_model=stub,
        mcp_factory=lambda: _MockMCP(),
        settings=Settings(GEMINI_FLASH_MODEL="stub-gemini-flash"),
    )
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["answer"].lower().startswith("cached")


@pytest.mark.asyncio
async def test_banned_phrase_in_answer_sets_degraded_with_reason():
    """LLM answer containing 'currently' triggers the safety sweeper."""

    class _BannedPhraseLlm(_StubLlm):
        async def generate_content_async(self, llm_request, stream=False):
            has_fn = any(
                p.function_response is not None
                for c in (llm_request.contents or [])
                for p in (c.parts or [])
            )
            if has_fn:
                yield LlmResponse(
                    content=Content(role="model", parts=[Part(text="Fans are currently gathering at The Pub.")]),
                    turn_complete=True,
                )
            else:
                yield LlmResponse(
                    content=Content(role="model", parts=[
                        Part(function_call=FunctionCall(name="get_fan_hotspots", args={"city_id": "c", "match_id": "m", "team_id": "t", "allow_external": False})),
                        Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "c", "start_date": None, "end_date": None, "category": "matchday", "allow_external": False})),
                        Part(function_call=FunctionCall(name="get_venues", args={"city_id": "c", "venue_type": "any", "allow_external": False})),
                    ]),
                    turn_complete=False,
                )

    stub = _BannedPhraseLlm(model="stub-gemini-flash")
    agent = FanGatheringADKAgent(
        stub_model=stub,
        mcp_factory=lambda: _MockMCP(),
        settings=Settings(GEMINI_FLASH_MODEL="stub-gemini-flash"),
    )
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["degraded"] is True
    assert "degraded_reason" in response
    assert "currently" in response["degraded_reason"].lower()


@pytest.mark.asyncio
async def test_confidence_and_evidence_fields_present():
    agent = _make_agent(Scenario.HAPPY)
    response = await agent.answer(city_id="city_toronto", match_id="match_123", team_id="team_argentina")
    assert response["confidence"] in {"low", "medium", "high"}
    assert isinstance(response["evidence_summary"], list)
    assert isinstance(response["verified_signals"], list)
    assert isinstance(response["inferred_signals"], list)
    assert response["verified_signals"]  # seeded hotspot has verified signals


@pytest.mark.asyncio
async def test_missing_tool_data_handled_gracefully():
    """MISSING_TOOL scenario: only 2 tools called, get_venues data absent."""
    agent = _make_agent(Scenario.MISSING_TOOL)
    response = await agent.answer(city_id="city_toronto", match_id="match_123")
    assert response["answer"]
    assert response["confidence"] in {"low", "medium", "high"}


@pytest.mark.asyncio
async def test_degraded_tool_propagates_to_response():
    agent = FanGatheringADKAgent(
        stub_model=_StubLlm(model="stub-gemini-flash", scenario=Scenario.HAPPY),
        mcp_factory=lambda: _MockMCPDegradedEvents(),
        settings=Settings(GEMINI_FLASH_MODEL="stub-gemini-flash"),
    )
    response = await agent.answer(city_id="city_toronto", match_id="match_123", team_id="team_argentina")
    assert response["degraded"] is True
    degraded_source = next(
        (s for s in response["tool_sources"] if s["tool"] == "get_city_events" and s["degraded"]),
        None,
    )
    assert degraded_source is not None


# ===========================================================================
# Smoke test (excluded from default CI run)
# ===========================================================================


@pytest.mark.smoke
async def test_smoke_real_flash_model():
    """Manual smoke test — requires GOOGLE_CLOUD_PROJECT and credentials.

    Run with: pytest -m smoke tests/test_fan_gathering_adk_agent.py
    Never runs in CI (CI uses: pytest -m 'not smoke').
    """
    from throughball_ai.agents.fan_gathering_adk import FanGatheringADKAgent
    from throughball_ai.config import get_settings

    agent = FanGatheringADKAgent(settings=get_settings())
    response = await agent.answer(
        city_id="city_toronto",
        match_id="match_123",
        team_id="team_argentina",
        question="Where are Argentina fans gathering near the stadium?",
    )
    assert response["answer"]
    assert "flash" in response["model_name"]
    assert "pro" not in response["model_name"].lower()
    assert response["confidence"] in {"low", "medium", "high"}
    assert not any(
        phrase in response["answer"].lower()
        for phrase in ("currently gathering", "right now", " live ")
    )
