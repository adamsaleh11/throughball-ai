"""Tests for the ADK-backed ItineraryAgent (03-07).

Stub model: _StubLlm subclasses BaseLlm — no live API calls.
MCP layer: real seeded MCP server injected via mcp_factory=build_mcp_server, so the
agent exercises the real get_venues / get_city_events / get_route_context /
generate_itinerary tools end to end. Flash-only: there is no Pro path.
"""
from __future__ import annotations

from enum import Enum
from typing import AsyncGenerator

import pytest
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai.types import Content, FunctionCall, Part

from throughball_ai.agents.itinerary_adk import ItineraryADKAgent
from throughball_ai.mcp.server import build_mcp_server


def _usage():
    class _U:
        prompt_token_count = 120
        candidates_token_count = 80
        total_token_count = 200
    return _U()


class Scenario(str, Enum):
    HAPPY = "happy"            # gather venues+events, order, generate_itinerary → final text
    EXCEED = "exceed"          # five tool calls attempted → budget blocks the 5th
    HALLUCINATED = "hallucinated"  # generate_itinerary with an id not in gathered candidates


_FINAL_TEXT = (
    "Here is a matchday-anchored plan: a supporters pub before kickoff, the match at "
    "BMO Field, and a relaxed second day. Sequencing favors your interests and budget."
)

_ORDERED = ["venue_pub_1", "venue_bmo_field"]
_ORDERED_HALLUCINATED = ["venue_pub_1", "venue_does_not_exist", "venue_bmo_field"]


# Module-level model-invocation counter (BaseLlm is a frozen-ish pydantic model).
INVOCATIONS = {"count": 0}


class _StubLlm(BaseLlm):
    model_name: str = "stub-gemini-flash"
    scenario: str = Scenario.HAPPY

    @classmethod
    def supported_models(cls):
        return ["stub-gemini-flash"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        INVOCATIONS["count"] += 1
        has_fn_resp = any(
            p.function_response is not None
            for c in (llm_request.contents or [])
            for p in (c.parts or [])
        )
        if has_fn_resp:
            yield LlmResponse(
                content=Content(role="model", parts=[Part(text=_FINAL_TEXT)]),
                usage_metadata=_usage(),
                model_version="gemini-2.0-flash-001",
                turn_complete=True,
            )
            return

        base_args = {
            "city_id": "city_toronto",
            "match_id": "match_123",
        }
        if self.scenario == Scenario.EXCEED:
            calls = [
                Part(function_call=FunctionCall(name="get_venues", args={"city_id": "city_toronto"})),
                Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "city_toronto"})),
                Part(function_call=FunctionCall(name="get_route_context", args={
                    "city_id": "city_toronto",
                    "origin": {"type": "venue", "id": "venue_pub_1"},
                    "destination": {"type": "venue", "id": "venue_bmo_field"},
                    "mode": "transit",
                })),
                Part(function_call=FunctionCall(name="get_venues", args={"city_id": "city_toronto"})),
                Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "city_toronto"})),
            ]
        else:
            ordered = _ORDERED_HALLUCINATED if self.scenario == Scenario.HALLUCINATED else _ORDERED
            calls = [
                Part(function_call=FunctionCall(name="get_venues", args={"city_id": "city_toronto"})),
                Part(function_call=FunctionCall(name="get_city_events", args={"city_id": "city_toronto"})),
                Part(function_call=FunctionCall(name="generate_itinerary", args={
                    **base_args,
                    "ordered_candidate_ids": ordered,
                    "traveler_profile": {"party_size": 2, "budget": "medium", "interests": ["supporter pubs"]},
                    "start_date": "2026-06-18",
                    "end_date": "2026-06-20",
                })),
            ]
        yield LlmResponse(
            content=Content(role="model", parts=calls),
            usage_metadata=_usage(),
            model_version="gemini-2.0-flash-001",
            turn_complete=False,
        )


@pytest.fixture(autouse=True)
def _reset_state():
    ItineraryADKAgent._cache.clear()
    ItineraryADKAgent._locks.clear()
    INVOCATIONS["count"] = 0
    yield
    ItineraryADKAgent._cache.clear()
    ItineraryADKAgent._locks.clear()


def _agent(scenario=Scenario.HAPPY):
    return ItineraryADKAgent(
        stub_model=_StubLlm(model="stub-gemini-flash", scenario=scenario),
        mcp_factory=build_mcp_server,
    )


async def _run(scenario=Scenario.HAPPY):
    return await _agent(scenario).generate(
        city_id="city_toronto",
        match_id="match_123",
        traveler_profile={"party_size": 2, "budget": "medium", "interests": ["supporter pubs"]},
        start_date="2026-06-18",
        end_date="2026-06-20",
    )


@pytest.mark.asyncio
async def test_generate_returns_day_structured_itinerary_with_reasoning_and_confidence():
    result = await _run()
    itinerary = result["itinerary"]
    assert isinstance(itinerary["days"], list) and len(itinerary["days"]) >= 1
    day = itinerary["days"][0]
    assert "date" in day and isinstance(day["items"], list)
    assert result["reasoning"]
    assert result["confidence"] in ("low", "medium", "high")
    assert result["model_name"]


# --- Phase 3: budget + telemetry ---

@pytest.mark.asyncio
async def test_tool_call_budget_blocks_fifth_call():
    agent = _agent(Scenario.EXCEED)
    result = await agent.generate(
        city_id="city_toronto", match_id="match_123",
        traveler_profile={"budget": "medium"},
        start_date="2026-06-18", end_date="2026-06-20",
    )
    # The 5th scripted tool call must be blocked by the budget guard.
    assert result["metrics"]["tool_call_count"] <= 4


@pytest.mark.asyncio
async def test_run_emits_metrics_and_uses_flash_model_name():
    result = await _run()
    assert "metrics" in result
    assert result["metrics"]["tool_call_count"] >= 1
    assert "tool_latencies" in result["metrics"]


# --- Phase 4: self-check, confidence, assumptions ---

@pytest.mark.asyncio
async def test_hallucinated_item_marks_degraded():
    result = await _run(Scenario.HALLUCINATED)
    assert result["self_check"]["passed"] is False
    assert "venue_does_not_exist" in result["self_check"]["reason"]
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_assumptions_include_honesty_and_budget_rationale():
    result = await _run()
    text = " ".join(result["assumptions"]).lower()
    assert "matchday-anchored" in text
    assert "budget" in text


@pytest.mark.asyncio
async def test_full_grounding_yields_high_confidence():
    # HAPPY gathers venues + events but no route_context → medium at best.
    result = await _run()
    assert result["confidence"] in ("medium", "high")
    assert result["self_check"]["passed"] is True


# --- Phase 5: second-layer cache ---

@pytest.mark.asyncio
async def test_duplicate_request_reuses_cache_without_invoking_model():
    agent = _agent()
    first = await agent.generate(
        city_id="city_toronto", match_id="match_123",
        traveler_profile={"budget": "medium"},
        start_date="2026-06-18", end_date="2026-06-20",
    )
    invocations_after_first = INVOCATIONS["count"]
    assert first["cache_hit"] is False

    second = await agent.generate(
        city_id="city_toronto", match_id="match_123",
        traveler_profile={"budget": "medium"},
        start_date="2026-06-18", end_date="2026-06-20",
    )
    assert second["cache_hit"] is True
    assert INVOCATIONS["count"] == invocations_after_first
    assert second["itinerary"] == first["itinerary"]


@pytest.mark.asyncio
async def test_different_input_misses_cache():
    agent = _agent()
    await agent.generate(
        city_id="city_toronto", match_id="match_123",
        traveler_profile={"budget": "medium"},
        start_date="2026-06-18", end_date="2026-06-20",
    )
    invocations_after_first = INVOCATIONS["count"]
    other = await agent.generate(
        city_id="city_toronto", match_id="match_123",
        traveler_profile={"budget": "high"},  # changed key → miss
        start_date="2026-06-18", end_date="2026-06-20",
    )
    assert other["cache_hit"] is False
    assert INVOCATIONS["count"] > invocations_after_first


@pytest.mark.asyncio
async def test_concurrent_identical_requests_invoke_model_once():
    agent = _agent()
    import asyncio as _asyncio
    results = await _asyncio.gather(*[
        agent.generate(
            city_id="city_toronto", match_id="match_123",
            traveler_profile={"budget": "medium"},
            start_date="2026-06-18", end_date="2026-06-20",
        )
        for _ in range(3)
    ])
    # Exactly one run populated the cache; the other two are cache hits.
    cache_hits = [r["cache_hit"] for r in results]
    assert cache_hits.count(False) == 1
    assert cache_hits.count(True) == 2
