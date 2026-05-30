"""ADK-backed Itinerary Agent (03-07).

Implements ItineraryADKAgent as a google.adk.agents.LlmAgent wrapper. The LLM owns
sequencing (ReAct): it gathers candidates (get_venues, get_city_events), optionally
probes get_route_context, filters by budget/interests, orders candidates, then calls
generate_itinerary LAST to format them. generate_itinerary is a pure formatter — it
never computes ordering. Sequencing is matchday-anchored, not geographically
optimized, and the agent says so honestly in `assumptions`.

Python enforces the 4-tool-call budget, runs a deterministic bounded self-check,
computes confidence, emits telemetry, and caches results by input hash (a second
layer above the MCP middleware cache).

Flash-only by design: no Pro model, no escalation, no model routing.

# HTTP: wired in Phase 06-01 via POST /agents/itinerary/generate
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import InMemoryRunner, RunConfig
from google.genai.types import Content, GenerateContentConfig, Part

from throughball_ai.adk.metrics import build_llm_metrics
from throughball_ai.config import Settings, get_settings
from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.trace import new_id

AGENT_NAME = "itinerary"
_MAX_TOOL_CALLS = 4
_MAX_DAYS = 3
_MAX_ITEMS_PER_DAY = 4
_AGENT_MAX_OUTPUT_TOKENS = 512

_TOOL_NAMES = ("get_venues", "get_city_events", "get_route_context", "generate_itinerary")

_SYSTEM_INSTRUCTION = (
    "You are the Itinerary Planner for the Throughball FIFA World Cup companion app. "
    "You build a multi-day, match-aware plan from seeded data.\n\n"
    "TOOLS (use the minimum needed — tool calls cost money):\n"
    "- get_venues: gather candidate venues (supporter pubs, fan zones, the stadium).\n"
    "- get_city_events: gather candidate events (matchday events, watch parties).\n"
    "- get_route_context: OPTIONAL — approximate transit context between two points.\n"
    "- generate_itinerary: call this LAST, passing your ordered_candidate_ids. It only "
    "formats; it does not order.\n\n"
    f"You have at most {_MAX_TOOL_CALLS} tool calls.\n\n"
    "PLANNING RULES:\n"
    "- Filter candidates by the traveler's budget and interests.\n"
    "- YOU decide the order of candidates; generate_itinerary just lays them onto days.\n"
    "- Sequencing is matchday-anchored (built around kickoff), NOT geographically "
    "optimized. Do not claim stops are arranged by travel distance.\n"
    f"- Keep it small: at most {_MAX_DAYS} days and {_MAX_ITEMS_PER_DAY} items per day.\n"
    "- Be concise."
)


class ItineraryADKAgent:
    """ADK LlmAgent wrapper for itinerary planning.

    Args:
        stub_model: Inject a BaseLlm subclass for tests. None = production (Flash).
        mcp_factory: Factory returning an MCP server instance. Injected in tests.
        settings: App settings. Defaults to get_settings().
        metrics_writer: Optional callable receiving the final run-completed event.
    """

    # Class-level second-layer cache + per-key locks, shared across instances so
    # duplicate requests reuse results even through fresh agent objects.
    _cache: dict[str, dict] = {}
    _locks: dict[str, asyncio.Lock] = {}

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

    @classmethod
    def _cache_key(cls, city_id, match_id, traveler_profile, start_date, end_date) -> str:
        payload = json.dumps(
            {
                "city_id": city_id,
                "match_id": match_id,
                "traveler_profile": traveler_profile or {},
                "start_date": start_date,
                "end_date": end_date,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def generate(
        self,
        *,
        city_id: str,
        match_id: str,
        traveler_profile: Optional[dict] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        key = self._cache_key(city_id, match_id, traveler_profile, start_date, end_date)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached is not None:
                hit = dict(cached)
                hit["cache_hit"] = True
                return hit

            result = await self._run(
                city_id=city_id,
                match_id=match_id,
                traveler_profile=traveler_profile or {},
                start_date=start_date,
                end_date=end_date,
                session_id=session_id,
            )
            self._cache[key] = result
            out = dict(result)
            out["cache_hit"] = False
            return out

    async def _run(
        self,
        *,
        city_id: str,
        match_id: str,
        traveler_profile: dict,
        start_date: Optional[str],
        end_date: Optional[str],
        session_id: str,
    ) -> dict[str, Any]:
        run_start = time.monotonic()
        mcp = self._mcp_factory()

        tool_results: dict[str, dict] = {}
        tool_latencies: dict[str, int] = {}
        requested_candidate_ids: list[str] = []

        async def _call(name: str, args: dict) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(name, {**args, "allow_external": False})
                result = json.loads(raw[0].text)
            except Exception as exc:  # noqa: BLE001 — degrade, never raise into the LLM loop
                result = _degraded_tool_result(name, exc)
            tool_latencies[name] = int((time.monotonic() - t0) * 1000)
            tool_results[name] = result
            return result

        async def get_venues(city_id: str, venue_type: str = "any", limit: int = 20) -> dict:
            return await _call("get_venues", {"city_id": city_id, "venue_type": venue_type, "limit": limit})

        async def get_city_events(city_id: str, category: str = "any", limit: int = 20) -> dict:
            return await _call("get_city_events", {"city_id": city_id, "category": category, "limit": limit})

        async def get_route_context(city_id: str, origin: dict, destination: dict,
                                    mode: str = "any", departure_time: str = "") -> dict:
            return await _call("get_route_context", {
                "city_id": city_id, "origin": origin, "destination": destination,
                "mode": mode, "departure_time": departure_time or None,
            })

        async def generate_itinerary(city_id: str, match_id: str, ordered_candidate_ids: list,
                                     traveler_profile: dict = None, start_date: str = "",
                                     end_date: str = "") -> dict:
            requested_candidate_ids[:] = list(ordered_candidate_ids or [])
            return await _call("generate_itinerary", {
                "city_id": city_id, "match_id": match_id,
                "ordered_candidate_ids": ordered_candidate_ids,
                "traveler_profile": traveler_profile or {},
                "start_date": start_date or None, "end_date": end_date or None,
            })

        from throughball_ai.adk.callbacks import AdkCallbackHooks  # lazy — avoids adk↔telemetry cycle

        hooks = AdkCallbackHooks()
        request_id = new_id("req")
        trace_id = new_id("tr")
        agent_run_id = new_id("ar")

        def _before_tool(tool, args, tool_context):
            count = int(tool_context.state.get("tool_call_count", 0))
            if count >= _MAX_TOOL_CALLS:
                return {"error": f"Tool call budget exceeded (max {_MAX_TOOL_CALLS})."}
            tool_context.state["tool_call_count"] = count + 1
            return None

        def _after_tool(tool, args, tool_context, tool_response):
            is_degraded = (
                not tool_response.get("ok", True)
                or tool_response.get("telemetry", {}).get("degraded", False)
            )
            hooks.on_tool_completed(
                request_id=request_id, trace_id=trace_id, span_id=new_id("sp"),
                parent_span_id=agent_run_id, agent_run_id=agent_run_id, session_id=session_id,
                tool_call_id=new_id("tc"), tool_name=tool.name,
                status="degraded" if is_degraded else "ok",
                latency_ms=tool_latencies.get(tool.name, 0), degraded=is_degraded,
            )
            return None

        _model_call_start = [0.0]
        _model_version = [""]
        _usage: dict[str, int] = {}

        def _before_model(callback_context, llm_request):
            _model_call_start[0] = time.monotonic()
            return None

        def _after_model(callback_context, llm_response):
            if llm_response.model_version:
                _model_version[0] = llm_response.model_version
            model_latency = int((time.monotonic() - _model_call_start[0]) * 1000)
            usage_meta = getattr(llm_response, "usage_metadata", None)
            if usage_meta is not None and hasattr(usage_meta, "prompt_token_count"):
                _usage["prompt_tokens"] = usage_meta.prompt_token_count or 0
                _usage["completion_tokens"] = usage_meta.candidates_token_count or 0
                _usage["total_tokens"] = usage_meta.total_token_count or 0
            hooks.on_model_completed(
                request_id=request_id, trace_id=trace_id, span_id=new_id("sp"),
                parent_span_id=agent_run_id, agent_run_id=agent_run_id, session_id=session_id,
                model_name=_model_version[0] or self._model_name, latency_ms=model_latency,
                usage=dict(_usage), tool_call_count=len(tool_latencies),
            )
            return None

        model: Any = (
            self._stub_model if self._stub_model is not None else self._settings.gemini_flash_model
        )
        agent = LlmAgent(
            name=AGENT_NAME,
            model=model,
            instruction=_SYSTEM_INSTRUCTION,
            tools=[get_venues, get_city_events, get_route_context, generate_itinerary],
            before_tool_callback=_before_tool,
            after_tool_callback=_after_tool,
            before_model_callback=_before_model,
            after_model_callback=_after_model,
            generate_content_config=GenerateContentConfig(
                max_output_tokens=_AGENT_MAX_OUTPUT_TOKENS,
                temperature=self._settings.default_temperature,
            ),
        )

        runner = InMemoryRunner(agent=agent, app_name="throughball")
        session = await runner.session_service.create_session(
            app_name="throughball", user_id="itinerary_agent"
        )

        user_text = (
            f"Plan a {start_date}..{end_date} itinerary in {city_id} around match {match_id} "
            f"for traveler profile {json.dumps(traveler_profile)}."
        )

        events = []
        async for event in runner.run_async(
            user_id="itinerary_agent",
            session_id=session.id,
            new_message=Content(role="user", parts=[Part(text=user_text)]),
            state_delta={"tool_call_count": 0},
            run_config=RunConfig(max_llm_calls=self._settings.max_agent_iterations),
        ):
            events.append(event)

        reasoning = _extract_answer_text(events)
        itinerary = _extract_itinerary(tool_results)
        candidate_ids = _gathered_candidate_ids(tool_results)

        self_check = _self_check(
            itinerary, candidate_ids, requested_candidate_ids, start_date, end_date
        )
        any_tool_degraded = any(
            r.get("telemetry", {}).get("degraded") or not r.get("ok", True)
            for r in tool_results.values()
        )
        degraded = not self_check["passed"] or any_tool_degraded or not itinerary["days"]
        degraded_reason = None
        if not self_check["passed"]:
            degraded_reason = self_check["reason"]
        elif any_tool_degraded:
            degraded_reason = "One or more tools returned degraded data."
        elif not itinerary["days"]:
            degraded_reason = "No itinerary days could be assembled from available data."

        confidence = _compute_confidence(tool_results, itinerary, any_tool_degraded)
        assumptions = _assumptions(itinerary, traveler_profile)

        total_latency_ms = int((time.monotonic() - run_start) * 1000)
        model_name = _model_version[0] or self._model_name
        metrics = build_llm_metrics(
            model_name=model_name, latency_ms=total_latency_ms, usage=_usage,
            tool_call_count=len(tool_latencies), degraded=degraded,
        )
        metrics["total_latency_ms"] = total_latency_ms
        metrics["tool_latencies"] = dict(tool_latencies)

        hooks_event = hooks.on_agent_completed(
            request_id=request_id, trace_id=trace_id, span_id=new_id("sp"),
            parent_span_id=None, agent_run_id=agent_run_id, session_id=session.id,
            agent_name=AGENT_NAME, latency_ms=total_latency_ms, degraded=degraded,
            final_confidence=confidence["label"], tool_latencies=dict(tool_latencies),
        )
        if self._metrics_writer is not None:
            self._metrics_writer(hooks_event)

        return {
            "itinerary": itinerary,
            "reasoning": reasoning,
            "confidence": confidence["label"],
            "confidence_details": confidence,
            "assumptions": assumptions,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "self_check": self_check,
            "tool_sources": [_tool_source(r) for r in tool_results.values()],
            "model_name": model_name,
            "metrics": metrics,
            "cache_hit": False,
        }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


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


def _extract_answer_text(events: list) -> str:
    for event in reversed(events):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    return part.text
    return ""


def _extract_itinerary(tool_results: dict[str, dict]) -> dict:
    r = tool_results.get("generate_itinerary")
    if not r or not r.get("ok", False):
        return {"days": [], "assumptions": []}
    data = r.get("data", {}) or {}
    return {
        "itinerary_id": data.get("itinerary_id"),
        "city_id": data.get("city_id"),
        "match_id": data.get("match_id"),
        "days": data.get("days", []) or [],
        "assumptions": data.get("assumptions", []) or [],
    }


def _gathered_candidate_ids(tool_results: dict[str, dict]) -> set[str]:
    ids: set[str] = set()
    venues = tool_results.get("get_venues")
    if venues and venues.get("ok", False):
        for v in venues.get("data", {}).get("venues", []) or []:
            if v.get("venue_id"):
                ids.add(v["venue_id"])
    events = tool_results.get("get_city_events")
    if events and events.get("ok", False):
        for e in events.get("data", {}).get("events", []) or []:
            if e.get("event_id"):
                ids.add(e["event_id"])
    return ids


def _tool_source(result: dict) -> dict:
    tel = result.get("telemetry", {})
    return {
        "tool": result.get("tool", "unknown"),
        "source_type": result.get("source_type") or tel.get("source_type"),
        "degraded": bool(tel.get("degraded")) or not result.get("ok", True),
        "external_api_called": bool(tel.get("external_api_called")),
    }


# ---------------------------------------------------------------------------
# Bounded self-check (deterministic — no re-prompt loop)
# ---------------------------------------------------------------------------


def _self_check(itinerary: dict, candidate_ids: set[str], requested_ids: list[str],
                start_date, end_date) -> dict:
    # 0) Every candidate the LLM ordered must have actually been gathered. This catches
    #    hallucinated IDs even when the formatter silently drops the unknown ones.
    if candidate_ids:
        for rid in requested_ids:
            if rid not in candidate_ids:
                return {"passed": False,
                        "reason": f"Itinerary item '{rid}' was not in the gathered candidates."}

    days = itinerary.get("days", [])
    if not days:
        return {"passed": True, "reason": "No days to validate."}

    # 1) Every item_id must come from the gathered candidate set (no hallucinations).
    for day in days:
        for item in day.get("items", []):
            iid = item.get("item_id")
            if candidate_ids and iid not in candidate_ids:
                return {"passed": False,
                        "reason": f"Itinerary item '{iid}' was not in the gathered candidates."}

    # 2) Every day must fall within the requested date range.
    if start_date:
        for day in days:
            d = day.get("date")
            if d and (d < start_date or (end_date and d > end_date)):
                return {"passed": False,
                        "reason": f"Day '{d}' falls outside {start_date}..{end_date}."}

    # 3) No day may exceed the per-day item cap.
    for day in days:
        if len(day.get("items", [])) > _MAX_ITEMS_PER_DAY:
            return {"passed": False,
                    "reason": f"Day '{day.get('date')}' exceeds {_MAX_ITEMS_PER_DAY} items."}

    # 4) No emitted day may be empty (empty days are dropped, not unintentionally kept).
    for day in days:
        if not day.get("items"):
            return {"passed": False,
                    "reason": f"Day '{day.get('date')}' is unintentionally empty."}

    return {"passed": True, "reason": "All items grounded, in range, within caps, non-empty."}


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def _compute_confidence(tool_results: dict, itinerary: dict, any_tool_degraded: bool) -> dict:
    contributors: list[str] = []
    downgrade_reasons: list[str] = []

    has_venues = _ok(tool_results.get("get_venues"))
    has_events = _ok(tool_results.get("get_city_events"))
    has_route = _ok(tool_results.get("get_route_context"))
    has_days = bool(itinerary.get("days"))

    if has_venues:
        contributors.append("Venue candidates were gathered.")
    else:
        downgrade_reasons.append("No venue candidates gathered.")
    if has_events:
        contributors.append("Event candidates were gathered.")
    if has_route:
        contributors.append("Route context informed sequencing.")
    if any_tool_degraded:
        downgrade_reasons.append("One or more tools returned degraded data.")
    if not has_days:
        downgrade_reasons.append("No itinerary days assembled.")

    if not has_days or not has_venues or any_tool_degraded:
        label = "low"
    elif has_venues and has_events and has_route:
        label = "high"
    else:
        label = "medium"

    return {"label": label, "contributors": contributors, "downgrade_reasons": downgrade_reasons}


def _ok(result: Optional[dict]) -> bool:
    return bool(
        result
        and result.get("ok", False)
        and not result.get("telemetry", {}).get("degraded", False)
    )


def _assumptions(itinerary: dict, traveler_profile: dict) -> list[str]:
    assumptions = list(itinerary.get("assumptions", []))
    budget = (traveler_profile or {}).get("budget")
    if budget and not any("budget" in a.lower() for a in assumptions):
        assumptions.append(f"Recommendations were filtered for a '{budget}' budget.")
    return assumptions
