import pytest

from throughball_ai.agents.fan_gathering import FanGatheringAgent, FanGatheringRequest
from throughball_ai.config import Settings
from throughball_ai.model_router import ModelRouter


class _ToolResult:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMCP:
    async def call_tool(self, tool_name: str, args: dict):
        payloads = {
            "get_fan_hotspots": '{"ok":true,"tool":"get_fan_hotspots","source_type":"seeded","data":{"hotspots":[{"name":"Supporters Club","neighborhood":"Downtown","verified_signals":["Partner venue listing","Ticket scan data"],"inferred_signals":["Near transit"],"evidence_ids":[]}]},"telemetry":{"degraded":false,"external_api_called":false}}',
            "get_city_events": '{"ok":true,"tool":"get_city_events","source_type":"seeded","data":{"events":[{"name":"Official Fan Zone","category":"matchday"}]},"telemetry":{"degraded":false,"external_api_called":false}}',
            "get_venues": '{"ok":true,"tool":"get_venues","source_type":"seeded","data":{"venues":[{"name":"Stadium"}]},"telemetry":{"degraded":false,"external_api_called":false}}',
        }
        return [_ToolResult(payloads[tool_name])]


# ---------------------------------------------------------------------------
# Phase 1: Plan Step (Thought + Trace)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_adapter_is_called_with_request_and_tool_names():
    calls = []

    async def mock_plan(request, tool_names):
        calls.append({"question": request.question, "tools": sorted(tool_names)})
        return "I will check hotspots, events, and venues."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
    )

    await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    assert len(calls) == 1
    assert calls[0]["tools"] == sorted(["get_fan_hotspots", "get_city_events", "get_venues"])


@pytest.mark.asyncio
async def test_reasoning_step_trace_event_emitted_with_plan_and_tools():
    trace_events = []

    async def mock_plan(request, tool_names):
        return "Plan: check hotspots and events."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        reasoning_trace_writer=trace_events.append,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    step_events = [e for e in trace_events if e["event_type"] == "agent_reasoning_step"]
    assert len(step_events) == 1
    event = step_events[0]
    assert event["plan"] == "Plan: check hotspots and events."
    assert set(event["tools_used"]) == {"get_fan_hotspots", "get_city_events", "get_venues"}
    assert event["fallback_plan"] is False
    assert event["trace_id"] == response["telemetry"]["trace_id"]
    assert event["agent_run_id"] == response["telemetry"]["agent_run_id"]


@pytest.mark.asyncio
async def test_plan_adapter_failure_falls_back_to_canned_plan():
    trace_events = []

    async def failing_plan(request, tool_names):
        raise RuntimeError("Flash unavailable")

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=failing_plan,
        reasoning_trace_writer=trace_events.append,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    # agent still answers
    assert response["answer"]
    step_events = [e for e in trace_events if e["event_type"] == "agent_reasoning_step"]
    assert len(step_events) == 1
    assert step_events[0]["fallback_plan"] is True
    assert step_events[0]["plan"]  # non-empty canned string


# ---------------------------------------------------------------------------
# Phase 2: LLM Synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_adapter_result_becomes_the_answer():
    async def mock_plan(request, tool_names):
        return "Plan: check all sources."

    async def mock_synthesis(thought, tool_results, confidence, max_chars):
        return "Supporters Club in Downtown is the top seeded gathering lead."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=mock_synthesis,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    assert response["answer"] == "Supporters Club in Downtown is the top seeded gathering lead."


@pytest.mark.asyncio
async def test_synthesis_adapter_receives_thought_and_tool_results():
    received = {}

    async def mock_plan(request, tool_names):
        return "My plan string."

    async def mock_synthesis(thought, tool_results, confidence, max_chars):
        received["thought"] = thought
        received["tool_results"] = tool_results
        received["confidence"] = confidence
        received["max_chars"] = max_chars
        return "Seeded answer."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=mock_synthesis,
    )

    await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", max_answer_chars=300)
    )

    assert received["thought"] == "My plan string."
    assert len(received["tool_results"]) == 3
    assert received["confidence"]["label"] in {"low", "medium", "high"}
    assert received["max_chars"] == 300


@pytest.mark.asyncio
async def test_synthesis_adapter_failure_falls_back_to_deterministic_synthesizer():
    async def mock_plan(request, tool_names):
        return "Plan."

    async def failing_synthesis(thought, tool_results, confidence, max_chars):
        raise RuntimeError("synthesis failed")

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=failing_synthesis,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    # Falls back — answer still present and synthesis_fallback flagged
    assert response["answer"]
    assert response["telemetry"].get("synthesis_fallback") is True


@pytest.mark.asyncio
async def test_agent_run_completed_includes_self_check_passed_after_synthesis():
    captured = []

    async def mock_plan(request, tool_names):
        return "Plan."

    async def mock_synthesis(thought, tool_results, confidence, max_chars):
        return "Seeded matchday data suggests Supporters Club."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=mock_synthesis,
        metrics_writer=captured.append,
    )

    await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123", question="Where are Argentina fans?")
    )

    assert len(captured) == 1
    assert "self_check_passed" in captured[0]


# ---------------------------------------------------------------------------
# Phase 3: Groundedness Self-Check
# ---------------------------------------------------------------------------


def test_groundedness_check_fails_for_banned_phrase_against_seeded_data():
    from throughball_ai.agents.fan_gathering import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "seeded", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check("Fans are currently gathering at Supporters Club.", tool_results)

    assert result["passed"] is False
    assert result["reason"]


def test_groundedness_check_passes_for_grounded_answer_against_seeded_data():
    from throughball_ai.agents.fan_gathering import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "seeded", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check(
        "Seeded matchday data suggests Supporters Club as the top gathering lead.", tool_results
    )

    assert result["passed"] is True


def test_groundedness_check_passes_when_no_seeded_or_cached_data():
    from throughball_ai.agents.fan_gathering import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "live", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check("Fans are currently gathering at Supporters Club.", tool_results)

    assert result["passed"] is True


@pytest.mark.asyncio
async def test_agent_response_includes_self_check_field():
    async def mock_plan(request, tool_names):
        return "Plan."

    async def mock_synthesis(thought, tool_results, confidence, max_chars):
        return "Seeded matchday data suggests Supporters Club."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=mock_synthesis,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123")
    )

    assert "self_check" in response
    assert "passed" in response["self_check"]
    assert "reason" in response["self_check"]


@pytest.mark.asyncio
async def test_self_check_catches_hallucinated_freshness_in_synthesized_answer():
    async def mock_plan(request, tool_names):
        return "Plan."

    async def bad_synthesis(thought, tool_results, confidence, max_chars):
        return "Fans are currently gathering right now at the venue."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=bad_synthesis,
    )

    response = await agent.answer(
        FanGatheringRequest(city_id="city_toronto", match_id="match_123")
    )

    # answer is still returned even when self-check fails
    assert response["answer"]
    assert response["self_check"]["passed"] is False


# ---------------------------------------------------------------------------
# Phase 4: AgentCoordinator Protocol Stub
# ---------------------------------------------------------------------------


def test_agent_coordinator_protocol_is_importable():
    from throughball_ai.orchestrator import AgentCoordinator

    assert AgentCoordinator is not None


def test_fan_gathering_agent_accepts_coordinator_kwarg():
    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        coordinator=None,
    )
    assert agent is not None


@pytest.mark.asyncio
async def test_coordinator_delegate_is_never_called_during_answer():
    class _SpyCoordinator:
        called = False

        async def delegate(self, agent_name: str, request: dict) -> dict:
            _SpyCoordinator.called = True
            return {}

    async def mock_plan(request, tool_names):
        return "Plan."

    async def mock_synthesis(thought, tool_results, confidence, max_chars):
        return "Seeded answer."

    agent = FanGatheringAgent(
        model_router=ModelRouter(Settings()),
        mcp_factory=lambda: _StubMCP(),
        plan_adapter=mock_plan,
        synthesis_adapter=mock_synthesis,
        coordinator=_SpyCoordinator(),
    )

    await agent.answer(FanGatheringRequest(city_id="city_toronto", match_id="match_123"))

    assert _SpyCoordinator.called is False
