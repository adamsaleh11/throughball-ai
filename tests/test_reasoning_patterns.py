"""Reasoning-pattern tests migrated to the ADK-backed agent (03-04).

FanGatheringAgent (03-02) was replaced by FanGatheringADKAgent (03-04).
- plan step / synthesis adapter / reasoning trace tests were removed — the
  ADK runner owns that control flow and it is exercised via _StubLlm scenarios
  in test_fan_gathering_adk_agent.py instead.
- _groundedness_check is a pure helper that lives in fan_gathering_adk; its
  unit tests are preserved here verbatim.
- The AgentCoordinator protocol stub test is independent of the agent class
  and is unchanged.
"""
import pytest


# ---------------------------------------------------------------------------
# Phase 3 (migrated): Groundedness Self-Check — pure function unit tests
# ---------------------------------------------------------------------------


def test_groundedness_check_fails_for_banned_phrase_against_seeded_data():
    from throughball_ai.agents.fan_gathering_adk import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "seeded", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check("Fans are currently gathering at Supporters Club.", tool_results)

    assert result["passed"] is False
    assert result["reason"]


def test_groundedness_check_passes_for_grounded_answer_against_seeded_data():
    from throughball_ai.agents.fan_gathering_adk import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "seeded", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check(
        "Seeded matchday data suggests Supporters Club as the top gathering lead.", tool_results
    )

    assert result["passed"] is True


def test_groundedness_check_passes_when_no_seeded_or_cached_data():
    from throughball_ai.agents.fan_gathering_adk import _groundedness_check

    tool_results = [
        {"tool": "get_fan_hotspots", "source_type": "live", "ok": True, "data": {}, "telemetry": {}},
    ]
    result = _groundedness_check("Fans are currently gathering at Supporters Club.", tool_results)

    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Phase 4 (unchanged): AgentCoordinator Protocol Stub
# ---------------------------------------------------------------------------


def test_agent_coordinator_protocol_is_importable():
    from throughball_ai.orchestrator import AgentCoordinator

    assert AgentCoordinator is not None
