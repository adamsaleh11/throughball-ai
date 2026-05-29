import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from throughball_ai.config import Settings, get_settings
from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.trace import emit_reasoning_step_trace, new_id
from throughball_ai.model_router import ModelRoute, ModelRouter
from throughball_ai.telemetry import RunMetricsAccumulator

AGENT_NAME = "fan_gathering"

TEAM_ALIASES = {
    "argentina": "team_argentina",
    "brazil": "team_brazil",
    "canada": "team_canada",
}

_CANNED_PLAN = (
    "Calling get_fan_hotspots, get_city_events, and get_venues to answer the question."
)

_BANNED_FRESHNESS_PHRASES = (
    "currently",
    "right now",
    "live",
    "confirmed gathering",
    "are there now",
)

_SEEDED_SOURCE_TYPES = {"seeded", "cached"}

_TOOL_NAMES = ["get_fan_hotspots", "get_city_events", "get_venues"]


@dataclass(frozen=True)
class FanGatheringRequest:
    city_id: str
    match_id: str
    team_id: Optional[str] = None
    question: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_answer_chars: int = 480


def _groundedness_check(answer: str, tool_results: list[dict]) -> dict:
    has_seeded = any(
        r.get("source_type") in _SEEDED_SOURCE_TYPES for r in tool_results
    )
    if not has_seeded:
        return {"passed": True, "reason": "No seeded or cached data — freshness check not applicable."}

    lower = answer.lower()
    for phrase in _BANNED_FRESHNESS_PHRASES:
        if phrase in lower:
            return {
                "passed": False,
                "reason": (
                    f"Answer contains '{phrase}' but underlying data is seeded/cached, "
                    "not live confirmation."
                ),
            }

    return {"passed": True, "reason": "Answer is grounded — no banned freshness phrases detected."}


class FanGatheringAgent:
    def __init__(
        self,
        model_router: Optional[ModelRouter] = None,
        settings: Optional[Settings] = None,
        mcp_factory: Any = build_mcp_server,
        metrics_writer: Optional[Callable[[dict[str, Any]], None]] = None,
        plan_adapter: Optional[Callable] = None,
        synthesis_adapter: Optional[Callable] = None,
        llm_self_check: bool = False,
        coordinator: Any = None,
        reasoning_trace_writer: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._model_router = model_router or ModelRouter(self._settings)
        self._mcp_factory = mcp_factory
        self._metrics_writer = metrics_writer
        self._plan_adapter = plan_adapter
        self._synthesis_adapter = synthesis_adapter
        self._llm_self_check = llm_self_check
        self._coordinator = coordinator
        self._reasoning_trace_writer = reasoning_trace_writer

    async def answer(self, request: FanGatheringRequest) -> dict:
        agent_run_id = new_id("ar")
        trace_id = new_id("tr")
        session_id = new_id("sess")
        run_start = time.monotonic()

        accumulator = RunMetricsAccumulator(
            agent_run_id=agent_run_id,
            session_id=session_id,
            trace_id=trace_id,
            request_id=new_id("req"),
            agent_name=AGENT_NAME,
            writer=self._metrics_writer,
        )

        route = self._model_router.route(AGENT_NAME)

        # --- Phase 1: Plan (Thought) ---
        plan, fallback_plan = await self._run_plan_step(request, _TOOL_NAMES)

        emit_reasoning_step_trace(
            agent_run_id=agent_run_id,
            trace_id=trace_id,
            plan=plan,
            tools_used=_TOOL_NAMES,
            fallback_plan=fallback_plan,
            writer=self._reasoning_trace_writer,
        )

        # --- Phase 2: Act (Tools in parallel) ---
        team_id = request.team_id or _resolve_team_alias(request.question)
        fan_zone_question = _is_fan_zone_question(request.question)
        team_unresolved = team_id is None and not fan_zone_question
        mcp = self._mcp_factory()

        tool_specs = [
            (
                "get_fan_hotspots",
                {
                    "city_id": request.city_id,
                    "match_id": request.match_id,
                    "team_id": team_id or "team_unknown",
                    "allow_external": False,
                },
            ),
            (
                "get_city_events",
                {
                    "city_id": request.city_id,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "category": "matchday",
                    "allow_external": False,
                },
            ),
            (
                "get_venues",
                {
                    "city_id": request.city_id,
                    "venue_type": "any",
                    "allow_external": False,
                },
            ),
        ]

        results = await asyncio.gather(
            *[_call_tool_timed(mcp, name, args) for name, args in tool_specs],
            return_exceptions=True,
        )

        # --- Phase 3: Observe ---
        normalized = []
        for (name, _args), result in zip(tool_specs, results):
            if isinstance(result, Exception):
                accumulator.record_tool_call(name, latency_ms=0, degraded=True)
                normalized.append(_normalize_tool_result(name, result))
            else:
                tool_result, latency_ms = result
                degraded = bool(
                    tool_result.get("telemetry", {}).get("degraded")
                    or not tool_result.get("ok", True)
                )
                accumulator.record_tool_call(name, latency_ms=latency_ms, degraded=degraded)
                normalized.append(tool_result)

        confidence = _compute_confidence(normalized, team_unresolved=team_unresolved)

        # --- Phase 4: Answer + Self-Check ---
        synthesis_fallback = False
        if self._synthesis_adapter is not None:
            try:
                answer = await self._synthesis_adapter(
                    plan, normalized, confidence, request.max_answer_chars
                )
            except Exception:
                synthesis_fallback = True
                answer = _synthesize_answer(
                    normalized,
                    confidence,
                    request.max_answer_chars,
                    team_unresolved=team_unresolved,
                    fan_zone_question=fan_zone_question,
                )
        else:
            answer = _synthesize_answer(
                normalized,
                confidence,
                request.max_answer_chars,
                team_unresolved=team_unresolved,
                fan_zone_question=fan_zone_question,
            )

        self_check = _groundedness_check(answer, normalized)

        tool_sources = [_tool_source(result) for result in normalized]
        degraded = any(source["degraded"] for source in tool_sources)

        total_latency_ms = int((time.monotonic() - run_start) * 1000)
        accumulator.finalize(
            final_confidence=confidence["label"],
            total_latency_ms=total_latency_ms,
            self_check_passed=self_check["passed"],
        )

        telemetry: dict[str, Any] = {
            "agent_name": AGENT_NAME,
            "tool_calls": len(tool_specs),
            "selected_model": route.model,
            "degraded": degraded,
            "confidence": confidence["label"],
            "agent_run_id": agent_run_id,
            "trace_id": trace_id,
        }
        if synthesis_fallback:
            telemetry["synthesis_fallback"] = True

        return {
            "answer": answer,
            "confidence": confidence["label"],
            "evidence_summary": _evidence_summary(normalized),
            "verified_signals": _verified_signals(normalized),
            "inferred_signals": _inferred_signals(normalized),
            "confidence_details": confidence,
            "tool_sources": tool_sources,
            "degraded": degraded,
            "self_check": self_check,
            "telemetry": telemetry,
        }

    async def _run_plan_step(
        self, request: FanGatheringRequest, tool_names: list[str]
    ) -> tuple[str, bool]:
        if self._plan_adapter is None:
            return _CANNED_PLAN, True
        try:
            plan = await self._plan_adapter(request, tool_names)
            return plan, False
        except Exception:
            return _CANNED_PLAN, True


class GeminiFlashSynthesisAdapter:
    """Production Gemini Flash synthesis boundary.

    Tests construct this adapter and inspect route metadata, but do not invoke
    live inference. The live call path is intentionally isolated here.
    """

    def __init__(self, model_router: Optional[ModelRouter] = None) -> None:
        self._settings = get_settings()
        self._model_router = model_router or ModelRouter(self._settings)

    def route(self) -> ModelRoute:
        return self._model_router.route(AGENT_NAME)

    async def synthesize(self, prompt: str) -> str:
        route = self.route()
        if "pro" in route.model.lower():
            raise ValueError("Fan gathering synthesis must use Gemini Flash, not Gemini Pro.")

        from google import genai

        client = genai.Client(
            vertexai=self._settings.vertex_ai_enabled,
            project=self._settings.google_cloud_project,
            location=self._settings.google_cloud_location,
        )
        response = await client.aio.models.generate_content(
            model=route.model,
            contents=prompt,
        )
        return response.text or ""


async def _call_tool_timed(mcp: Any, tool_name: str, args: dict) -> tuple[dict, int]:
    t0 = time.monotonic()
    result = await mcp.call_tool(tool_name, args)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return json.loads(result[0].text), latency_ms


def _resolve_team_alias(question: Optional[str]) -> Optional[str]:
    if not question:
        return None
    lower = question.lower()
    for alias, team_id in TEAM_ALIASES.items():
        if alias in lower:
            return team_id
    return None


def _is_fan_zone_question(question: Optional[str]) -> bool:
    if not question:
        return False
    lower = question.lower()
    return "fan zone" in lower or "fanzone" in lower


def _normalize_tool_result(tool_name: str, result: Any) -> dict:
    if isinstance(result, Exception):
        return {
            "ok": True,
            "tool": tool_name,
            "source_type": None,
            "data": {},
            "telemetry": {
                "degraded": True,
                "degraded_reason": type(result).__name__,
                "external_api_called": False,
            },
        }
    return result


def _compute_confidence(results: list[dict], team_unresolved: bool = False) -> dict:
    verified = _verified_signals(results)
    inferred = _inferred_signals(results)
    degraded_tools = [
        result["tool"]
        for result in results
        if result.get("telemetry", {}).get("degraded") or not result.get("ok")
    ]
    contributors = []
    downgrade_reasons = []

    if verified:
        contributors.append("Verified hotspot signals are present.")
    if inferred:
        contributors.append("Inferred supporter-location signals are present.")
    if any(_events(result) for result in results):
        contributors.append("Matchday event data supports the recommendation.")
    if any(_venues(result) for result in results):
        contributors.append("Venue data supports the recommendation.")
    if degraded_tools:
        downgrade_reasons.append(f"Degraded tool results: {', '.join(degraded_tools)}.")
    if team_unresolved:
        downgrade_reasons.append("Could not resolve the team from the request.")
    if any(result.get("source_type") == "seeded" for result in results):
        downgrade_reasons.append("Seeded data is not live crowd confirmation.")

    label = "medium" if verified and not degraded_tools else "low"
    if len(verified) >= 2 and any(_events(result) for result in results) and not degraded_tools:
        label = "high"
    if not verified:
        label = "low"
    if team_unresolved:
        label = "low"

    return {
        "label": label,
        "contributors": contributors,
        "downgrade_reasons": downgrade_reasons,
    }


def _synthesize_answer(
    results: list[dict],
    confidence: dict,
    max_chars: int,
    team_unresolved: bool = False,
    fan_zone_question: bool = False,
) -> str:
    if fan_zone_question:
        event = next(
            (
                event
                for result in results
                for event in _events(result)
                if "fan zone" in event.get("name", "").lower()
            ),
            None,
        )
        if event:
            answer = (
                f"Seeded matchday data lists {event['name']} as the strongest fan zone lead. "
                f"Confidence is {confidence['label']}; this is not live confirmation of present crowd activity."
            )
            return answer[:max_chars]

    if team_unresolved:
        answer = (
            "Could not resolve the team from the request. Cached or seeded matchday data "
            "can suggest general supporter venues, but this is a low-confidence lead rather "
            "than team-specific evidence."
        )
        return answer[:max_chars]

    hotspot = next(iter(_hotspots(results)), None)
    if not hotspot:
        answer = (
            "Cached or seeded fan data does not identify a reliable gathering spot. "
            "Treat any venue suggestion as low confidence until fresher evidence is available."
        )
        return answer[:max_chars]

    venue_name = hotspot.get("name", "the top listed supporter venue")
    neighborhood = hotspot.get("neighborhood")
    location = f"{venue_name} in {neighborhood}" if neighborhood else venue_name
    answer = (
        f"Seeded matchday data suggests {location} as the best supporter gathering lead. "
        f"Confidence is {confidence['label']}: verified signals include "
        f"{'; '.join(hotspot.get('verified_signals', [])[:2]) or 'none'}, while inferred "
        f"signals include {'; '.join(hotspot.get('inferred_signals', [])[:2]) or 'none'}."
    )
    return answer[:max_chars]


def _evidence_summary(results: list[dict]) -> list[str]:
    summary = []
    for result in results:
        source_type = result.get("source_type") or result.get("telemetry", {}).get("source_type")
        summary.append(f"{result['tool']} returned {source_type or 'degraded'} data.")
    return summary


def _verified_signals(results: list[dict]) -> list[str]:
    signals = []
    for hotspot in _hotspots(results):
        signals.extend(hotspot.get("verified_signals", []))
    return signals


def _inferred_signals(results: list[dict]) -> list[str]:
    signals = []
    for hotspot in _hotspots(results):
        signals.extend(hotspot.get("inferred_signals", []))
    return signals


def _tool_source(result: dict) -> dict:
    telemetry = result.get("telemetry", {})
    return {
        "tool": result["tool"],
        "source_type": result.get("source_type") or telemetry.get("source_type"),
        "degraded": bool(telemetry.get("degraded")) or not result.get("ok", False),
        "external_api_called": bool(telemetry.get("external_api_called")),
    }


def _hotspots(results: list[dict]) -> list[dict]:
    for result in results:
        if result.get("tool") == "get_fan_hotspots":
            return result.get("data", {}).get("hotspots", [])
    return []


def _events(result: dict) -> list[dict]:
    if result.get("tool") != "get_city_events":
        return []
    return result.get("data", {}).get("events", [])


def _venues(result: dict) -> list[dict]:
    if result.get("tool") != "get_venues":
        return []
    return result.get("data", {}).get("venues", [])
