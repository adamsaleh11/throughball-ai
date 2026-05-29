import pytest

from throughball_ai.agents.fan_gathering import (
    FanGatheringAgent,
    FanGatheringRequest,
    GeminiFlashSynthesisAdapter,
)
from throughball_ai.config import Settings
from throughball_ai.model_router import ModelRouter


class _PartiallyDegradedMCP:
    async def call_tool(self, tool_name: str, args: dict):
        if tool_name == "get_city_events":
            raise TimeoutError("events unavailable")
        if tool_name == "get_fan_hotspots":
            return [
                _ToolResult(
                    """{"ok": true, "tool": "get_fan_hotspots", "source_type": "seeded", "data": {"hotspots": []}, "telemetry": {"degraded": false, "external_api_called": false}}"""
                )
            ]
        return [
            _ToolResult(
                """{"ok": true, "tool": "get_venues", "source_type": "seeded", "data": {"venues": []}, "telemetry": {"degraded": false, "external_api_called": false}}"""
            )
        ]


class _ToolResult:
    def __init__(self, text: str) -> None:
        self.text = text


class _PartiallyFailingMCP:
    async def call_tool(self, tool_name: str, args: dict):
        if tool_name == "get_city_events":
            raise TimeoutError("events unavailable")
        if tool_name == "get_fan_hotspots":
            return [
                _ToolResult(
                    """{"ok": true, "tool": "get_fan_hotspots", "source_type": "seeded", "data": {"hotspots": [{"name": "Fallback Pub", "neighborhood": "Downtown", "verified_signals": ["Partner venue listing"], "inferred_signals": ["Near transit"], "evidence_ids": []}]}, "telemetry": {"degraded": false, "external_api_called": false}}"""
                )
            ]
        return [
            _ToolResult(
                """{"ok": true, "tool": "get_venues", "source_type": "seeded", "data": {"venues": []}, "telemetry": {"degraded": false, "external_api_called": false}}"""
            )
        ]


@pytest.mark.asyncio
async def test_agent_answers_argentina_gathering_with_grounded_confidence():
    agent = FanGatheringAgent(model_router=ModelRouter(Settings()))

    response = await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            question="Where are Argentina fans gathering?",
            max_answer_chars=360,
        )
    )

    assert response["confidence"] in {"medium", "high"}
    assert "cached" in response["answer"].lower() or "seeded" in response["answer"].lower()
    assert "currently gathering" not in response["answer"].lower()
    assert response["evidence_summary"]
    assert response["verified_signals"]
    assert response["inferred_signals"]
    assert response["confidence_details"]["contributors"]
    assert len(response["tool_sources"]) == 3
    assert {source["tool"] for source in response["tool_sources"]} == {
        "get_fan_hotspots",
        "get_city_events",
        "get_venues",
    }
    assert all(source["external_api_called"] is False for source in response["tool_sources"])
    assert response["telemetry"]["agent_name"] == "fan_gathering"
    assert response["telemetry"]["tool_calls"] == 3
    assert "flash" in response["telemetry"]["selected_model"]
    assert len(response["answer"]) <= 360


@pytest.mark.asyncio
async def test_agent_handles_unknown_team_alias_as_low_confidence():
    agent = FanGatheringAgent(model_router=ModelRouter(Settings()))

    response = await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            question="Where are Atlantis fans gathering?",
        )
    )

    assert response["confidence"] == "low"
    assert any(
        "team" in reason.lower()
        for reason in response["confidence_details"]["downgrade_reasons"]
    )
    assert "could not resolve the team" in response["answer"].lower()


def test_gemini_flash_adapter_exposes_flash_route_without_live_call():
    adapter = GeminiFlashSynthesisAdapter(model_router=ModelRouter(Settings()))

    route = adapter.route()

    assert "flash" in route.model
    assert "pro" not in route.model.lower()
    assert route.agent_name == "fan_gathering"


@pytest.mark.asyncio
async def test_agent_answers_fan_zone_question_from_seeded_events_without_live_claims():
    agent = FanGatheringAgent(model_router=ModelRouter(Settings()))

    response = await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            question="Which fan zone is active?",
        )
    )

    assert "fan zone" in response["answer"].lower()
    assert "seeded" in response["answer"].lower() or "cached" in response["answer"].lower()
    assert "currently active" not in response["answer"].lower()


@pytest.mark.asyncio
async def test_answer_emits_run_summary_event_with_all_required_fields():
    captured = []
    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        metrics_writer=captured.append,
    )

    response = await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            question="Where are Argentina fans gathering?",
        )
    )

    assert len(captured) == 1
    event = captured[0]

    assert event["event_type"] == "agent_run_completed"
    assert event["tool_call_count"] == 3
    assert set(event["tool_latencies"].keys()) == {
        "get_fan_hotspots",
        "get_city_events",
        "get_venues",
    }
    assert event["final_confidence"] == response["confidence"]
    assert event["degraded"] == response["degraded"]
    assert event["agent_name"] == "fan_gathering"
    assert "agent_run_id" in response["telemetry"]
    assert "trace_id" in response["telemetry"]
    assert event["agent_run_id"] == response["telemetry"]["agent_run_id"]


@pytest.mark.asyncio
async def test_answer_emits_degraded_true_when_tool_fails():
    captured = []
    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _PartiallyDegradedMCP(),
        metrics_writer=captured.append,
    )

    await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            team_id="team_argentina",
        )
    )

    assert len(captured) == 1
    event = captured[0]
    assert event["degraded"] is True
    assert event["tool_call_count"] == 3


@pytest.mark.asyncio
async def test_agent_isolates_degraded_tool_results():
    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _PartiallyFailingMCP(),
    )

    response = await agent.answer(
        FanGatheringRequest(
            city_id="city_toronto",
            match_id="match_123",
            team_id="team_argentina",
        )
    )

    assert response["degraded"] is True
    assert response["confidence"] == "low"
    assert any(source["tool"] == "get_city_events" and source["degraded"] for source in response["tool_sources"])
    assert "Fallback Pub" in response["answer"]
