"""ADK-backed Fan Gathering Agent (03-04).

Implements FanGatheringADKAgent as a google.adk.agents.LlmAgent wrapper.
The LLM owns tool dispatch; Python enforces the tool-call budget (via
before_tool_callback / session state), applies safety post-processing, and
assembles the structured response from tool result events.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import InMemoryRunner, RunConfig
from google.genai.types import Content, GenerateContentConfig, Part

from throughball_ai.config import Settings, get_settings
from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.trace import new_id

AGENT_NAME = "fan_gathering"
_MAX_TOOL_CALLS = 3
_MAX_ANSWER_CHARS = 480  # mobile chat bubble limit without scroll

_BANNED_PHRASES = (
    "currently",
    "right now",
    " live ",
    "confirmed gathering",
    "are there now",
)

_SEEDED_SOURCE_TYPES = {"seeded", "cached"}

_TOOL_NAMES = ("get_fan_hotspots", "get_city_events", "get_venues")

_SYSTEM_INSTRUCTION = (
    "You are the Fan Gathering Agent for the Throughball FIFA World Cup companion app. "
    "You answer questions about where fans are gathering, best places to watch with supporters, "
    "and which fan zones are active.\n\n"
    "REQUIRED: Always call get_fan_hotspots, get_city_events, and get_venues before answering. "
    "Do not answer without calling all three tools.\n\n"
    "SAFETY RULES:\n"
    "- Never say 'currently', 'right now', 'live', 'confirmed gathering', or 'are there now' — "
    "the data is seeded/cached, not real-time.\n"
    "- Always begin your answer with 'Cached matchday data suggests…' when data comes from "
    "seeded or cached sources.\n"
    "- Distinguish verified signals (partner venue listings, event registrations) from inferred "
    "signals (proximity, transit access).\n"
    f"- Keep your answer under {_MAX_ANSWER_CHARS} characters."
)


class FanGatheringADKAgent:
    """ADK LlmAgent wrapper for fan gathering questions.

    Args:
        stub_model: Inject a BaseLlm subclass for tests. None = production (Flash).
        mcp_factory: Factory returning an MCP server instance. Injected in tests.
        settings: App settings. Defaults to get_settings().
        metrics_writer: Optional callable receiving the final run-completed event.
    """

    def __init__(
        self,
        *,
        stub_model: Optional[BaseLlm] = None,
        mcp_factory: Any = None,
        settings: Optional[Settings] = None,
        metrics_writer: Any = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._mcp_factory = mcp_factory or build_mcp_server
        self._stub_model = stub_model
        self._metrics_writer = metrics_writer

    @property
    def _model_name(self) -> str:
        if self._stub_model is not None:
            return self._stub_model.model_name
        return self._settings.gemini_flash_model

    async def answer(
        self,
        *,
        city_id: str,
        match_id: str,
        team_id: Optional[str] = None,
        question: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_answer_chars: int = _MAX_ANSWER_CHARS,
    ) -> dict[str, Any]:
        run_start = time.monotonic()
        mcp = self._mcp_factory()

        # --- Per-run accumulators (fresh per answer() call — safe for concurrent runs) ---
        tool_results: dict[str, dict] = {}
        tool_latencies: dict[str, int] = {}

        # --- MCP tool wrappers (FunctionTool callables) ---
        async def get_fan_hotspots(
            city_id: str,
            match_id: str,
            team_id: str,
            allow_external: bool = False,
        ) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_fan_hotspots",
                    {"city_id": city_id, "match_id": match_id, "team_id": team_id, "allow_external": allow_external},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = _degraded_tool_result("get_fan_hotspots", exc)
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_fan_hotspots"] = result
            tool_latencies["get_fan_hotspots"] = latency
            return result

        async def get_city_events(
            city_id: str,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            category: str = "matchday",
            allow_external: bool = False,
        ) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_city_events",
                    {"city_id": city_id, "start_date": start_date, "end_date": end_date, "category": category, "allow_external": allow_external},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = _degraded_tool_result("get_city_events", exc)
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_city_events"] = result
            tool_latencies["get_city_events"] = latency
            return result

        async def get_venues(
            city_id: str,
            venue_type: str = "any",
            allow_external: bool = False,
        ) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_venues",
                    {"city_id": city_id, "venue_type": venue_type, "allow_external": allow_external},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = _degraded_tool_result("get_venues", exc)
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_venues"] = result
            tool_latencies["get_venues"] = latency
            return result

        # --- Budget callback — counter in ADK session state, not closure ---
        def _before_tool(tool, args, tool_context):
            count = int(tool_context.state.get("tool_call_count", 0))
            if count >= _MAX_TOOL_CALLS:
                return {"error": f"Tool call budget exceeded (max {_MAX_TOOL_CALLS})."}
            tool_context.state["tool_call_count"] = count + 1
            return None

        # --- Model callback — capture model version for response ---
        _model_version: list[str] = [""]

        def _after_model(callback_context, llm_response):
            if llm_response.model_version:
                _model_version[0] = llm_response.model_version
            return None

        # --- Build agent and runner ---
        model: Any = self._stub_model if self._stub_model is not None else self._settings.gemini_flash_model
        agent = LlmAgent(
            name=AGENT_NAME,
            model=model,
            instruction=_SYSTEM_INSTRUCTION,
            tools=[get_fan_hotspots, get_city_events, get_venues],
            before_tool_callback=_before_tool,
            after_model_callback=_after_model,
            generate_content_config=GenerateContentConfig(
                max_output_tokens=self._settings.max_output_tokens,
                temperature=self._settings.default_temperature,
            ),
        )

        runner = InMemoryRunner(agent=agent, app_name="throughball")
        session = await runner.session_service.create_session(
            app_name="throughball", user_id="fan_agent"
        )

        # Compose user message
        user_text = question or f"Where are fans gathering near the stadium? City: {city_id}, Match: {match_id}"
        if team_id and not question:
            user_text += f", Team: {team_id}"

        events = []
        async for event in runner.run_async(
            user_id="fan_agent",
            session_id=session.id,
            new_message=Content(role="user", parts=[Part(text=user_text)]),
            state_delta={"tool_call_count": 0},
            run_config=RunConfig(max_llm_calls=self._settings.max_agent_iterations),
        ):
            events.append(event)

        # --- Post-processing ---
        answer_text = _extract_answer_text(events)
        results_list = _build_results_list(tool_results)

        answer_text, degraded_flag, degraded_reason = _apply_safety(answer_text, results_list)
        answer_text = answer_text[:max_answer_chars]

        any_tool_degraded = any(
            r.get("telemetry", {}).get("degraded") or not r.get("ok", True)
            for r in results_list
        )
        degraded = degraded_flag or any_tool_degraded or not results_list

        confidence = _compute_confidence(results_list)

        total_latency_ms = int((time.monotonic() - run_start) * 1000)
        tool_call_count = len(tool_latencies)
        model_name = _model_version[0] or self._model_name

        # Emit agent_run_completed via hooks
        agent_run_id = new_id("ar")
        trace_id = new_id("tr")
        span_id = new_id("sp")
        session_id = session.id

        from throughball_ai.adk.callbacks import AdkCallbackHooks  # lazy — avoids adk↔telemetry cycle
        hooks = AdkCallbackHooks()
        hooks_event = hooks.on_agent_completed(
            request_id=new_id("req"),
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            agent_run_id=agent_run_id,
            session_id=session_id,
            agent_name=AGENT_NAME,
            latency_ms=total_latency_ms,
            degraded=degraded,
            final_confidence=confidence["label"],
            tool_latencies=dict(tool_latencies),
        )

        if self._metrics_writer is not None:
            self._metrics_writer(hooks_event)

        return {
            "answer": answer_text,
            "confidence": confidence["label"],
            "evidence_summary": _evidence_summary(results_list),
            "verified_signals": _verified_signals(results_list),
            "inferred_signals": _inferred_signals(results_list),
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "tool_sources": [_tool_source(r) for r in results_list],
            "model_name": model_name,
            "metrics": {
                "tool_call_count": tool_call_count,
                "total_latency_ms": total_latency_ms,
                "tool_latencies": dict(tool_latencies),
            },
            "confidence_details": confidence,
            "self_check": _groundedness_check(answer_text, results_list),
        }


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------


def _apply_safety(
    answer: str,
    results: list[dict],
) -> tuple[str, bool, Optional[str]]:
    """Apply prefix enforcer and banned-phrase sweeper. Returns (answer, degraded, reason)."""
    has_seeded = any(r.get("source_type") in _SEEDED_SOURCE_TYPES for r in results)

    # Banned-phrase sweep — check before prefix injection so we see the raw answer
    lower = answer.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            return answer, True, f"Answer contains banned freshness phrase: '{phrase}'."

    # Prefix enforcer — inject only when seeded/cached data is present
    if has_seeded and not lower.startswith("cached"):
        answer = "Cached matchday data suggests " + answer[0].lower() + answer[1:]

    return answer, False, None


def _groundedness_check(answer: str, results: list[dict]) -> dict:
    has_seeded = any(r.get("source_type") in _SEEDED_SOURCE_TYPES for r in results)
    if not has_seeded:
        return {"passed": True, "reason": "No seeded/cached data — freshness check not applicable."}
    lower = answer.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            return {
                "passed": False,
                "reason": f"Answer contains '{phrase}' but underlying data is seeded/cached.",
            }
    return {"passed": True, "reason": "Answer is grounded — no banned freshness phrases detected."}


# ---------------------------------------------------------------------------
# Event extraction helpers
# ---------------------------------------------------------------------------


def _extract_answer_text(events: list) -> str:
    for event in reversed(events):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    return part.text
    return ""


def _build_results_list(tool_results: dict[str, dict]) -> list[dict]:
    """Return results in canonical order, inserting a degraded placeholder for missing tools."""
    out = []
    for name in _TOOL_NAMES:
        if name in tool_results:
            out.append(tool_results[name])
        # Omit missing tools from list — MISSING_TOOL scenario is handled gracefully
    return out


# ---------------------------------------------------------------------------
# Confidence and evidence helpers (ported from fan_gathering.py)
# ---------------------------------------------------------------------------


def _compute_confidence(results: list[dict]) -> dict:
    verified = _verified_signals(results)
    inferred = _inferred_signals(results)
    degraded_tools = [
        r.get("tool", "unknown")
        for r in results
        if r.get("telemetry", {}).get("degraded") or not r.get("ok", True)
    ]
    contributors = []
    downgrade_reasons = []

    if verified:
        contributors.append("Verified hotspot signals are present.")
    if inferred:
        contributors.append("Inferred supporter-location signals are present.")
    if any(_events(r) for r in results):
        contributors.append("Matchday event data supports the recommendation.")
    if any(_venues(r) for r in results):
        contributors.append("Venue data supports the recommendation.")
    if degraded_tools:
        downgrade_reasons.append(f"Degraded tool results: {', '.join(degraded_tools)}.")
    if any(r.get("source_type") == "seeded" for r in results):
        downgrade_reasons.append("Seeded data is not live crowd confirmation.")

    if not results:
        return {"label": "low", "contributors": [], "downgrade_reasons": ["No tool results available."]}

    label = "medium" if verified and not degraded_tools else "low"
    if len(verified) >= 2 and any(_events(r) for r in results) and not degraded_tools:
        label = "high"
    if not verified:
        label = "low"

    return {"label": label, "contributors": contributors, "downgrade_reasons": downgrade_reasons}


def _evidence_summary(results: list[dict]) -> list[str]:
    return [
        f"{r.get('tool', 'unknown')} returned {r.get('source_type') or r.get('telemetry', {}).get('source_type') or 'degraded'} data."
        for r in results
    ]


def _verified_signals(results: list[dict]) -> list[str]:
    signals: list[str] = []
    for h in _hotspots(results):
        signals.extend(h.get("verified_signals", []))
    return signals


def _inferred_signals(results: list[dict]) -> list[str]:
    signals: list[str] = []
    for h in _hotspots(results):
        signals.extend(h.get("inferred_signals", []))
    return signals


def _tool_source(result: dict) -> dict:
    tel = result.get("telemetry", {})
    return {
        "tool": result.get("tool", "unknown"),
        "source_type": result.get("source_type") or tel.get("source_type"),
        "degraded": bool(tel.get("degraded")) or not result.get("ok", True),
        "external_api_called": bool(tel.get("external_api_called")),
    }


def _hotspots(results: list[dict]) -> list[dict]:
    for r in results:
        if r.get("tool") == "get_fan_hotspots":
            return r.get("data", {}).get("hotspots", [])
    return []


def _events(result: dict) -> list[dict]:
    if result.get("tool") != "get_city_events":
        return []
    return result.get("data", {}).get("events", [])


def _venues(result: dict) -> list[dict]:
    if result.get("tool") != "get_venues":
        return []
    return result.get("data", {}).get("venues", [])


def _degraded_tool_result(tool_name: str, exc: Exception) -> dict:
    return {
        "ok": False,
        "tool": tool_name,
        "source_type": None,
        "data": {},
        "telemetry": {
            "degraded": True,
            "degraded_reason": type(exc).__name__,
            "external_api_called": False,
        },
    }
