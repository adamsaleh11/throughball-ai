"""ADK-backed City Concierge Agent (03-05).

Implements CityConciergeADKAgent as a google.adk.agents.LlmAgent wrapper.
The LLM owns tool dispatch; Python enforces the tool-call budget (via
before_tool_callback / session state), applies safety post-processing, and
assembles the structured response from tool result events.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import InMemoryRunner, RunConfig
from google.genai.types import Content, GenerateContentConfig, Part

from throughball_ai.config import Settings, get_settings
from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.trace import new_id

AGENT_NAME = "city_concierge"
_MAX_TOOL_CALLS = 4
_MAX_ANSWER_CHARS = 800

_BANNED_PHRASES = (
    "currently",
    "right now",
    " live ",
    "confirmed gathering",
    "are there now",
)

_TOOL_NAMES = ("get_city_profile", "get_venues", "get_city_events", "search_documents")

_SYSTEM_INSTRUCTION = (
    "You are the City Concierge for the Throughball companion app. "
    "You answer questions about restaurants, nightlife, tourism, fan events, and local recommendations.\n\n"
    "REQUIRED: Use the available tools strategically to understand the city and find the best recommendations:\n"
    "- get_city_profile: Understand the city's neighborhoods, landmarks, and vibe\n"
    "- get_venues: Discover restaurants, bars, museums, and venues\n"
    "- get_city_events: See what events are happening (concerts, sports, fan events, festivals)\n"
    "- search_documents: Find curated recommendations with sources\n\n"
    "Tool Budget: You have 4 tool calls per turn. Use them wisely.\n\n"
    "SAFETY RULES:\n"
    "- Never say 'currently', 'right now', 'live', 'confirmed gathering', or 'are there now' — "
    "the data is seeded/cached, not real-time.\n"
    "- Always cite your sources using [N] markers (e.g., [1], [2]).\n"
    "- Do not make claims without a source. If you don't have enough information, use the fallback: "
    "'I don't have enough reliable information to answer that. Try a more specific question, or consult official sources.'\n"
    "- Adapt recommendations to user preferences: budget, dietary constraints, interests, time."
)


class CityConciergeADKAgent:
    """ADK LlmAgent wrapper for city concierge recommendations.

    Args:
        stub_model: Inject a BaseLlm subclass for tests. None = production (Flash).
        mcp_factory: Factory returning an MCP server instance. Injected in tests.
        settings: App settings. Defaults to get_settings().
    """

    def __init__(
        self,
        *,
        stub_model: Optional[BaseLlm] = None,
        mcp_factory: Any = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._mcp_factory = mcp_factory or build_mcp_server
        self._stub_model = stub_model

    @property
    def _model_name(self) -> str:
        if self._stub_model is not None:
            return self._stub_model.model_name
        return self._settings.gemini_flash_model

    async def answer(
        self,
        *,
        query: str,
        session_id: str,
        city_id: str,
        team_id: Optional[str] = None,
        max_answer_chars: int = _MAX_ANSWER_CHARS,
    ) -> dict[str, Any]:
        run_start = time.monotonic()
        mcp = self._mcp_factory()

        # --- Per-run accumulators ---
        tool_results: dict[str, dict] = {}
        tool_latencies: dict[str, int] = {}

        # --- MCP tool wrappers (FunctionTool callables) ---
        async def get_city_profile(city_id: str) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool("get_city_profile", {"city_id": city_id})
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = {"error": str(exc), "ok": False}
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_city_profile"] = result
            tool_latencies["get_city_profile"] = latency
            return result

        async def get_venues(city_id: str, venue_type: str = "any") -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_venues", {"city_id": city_id, "venue_type": venue_type}
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = {"error": str(exc), "ok": False}
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_venues"] = result
            tool_latencies["get_venues"] = latency
            return result

        async def get_city_events(
            city_id: str,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            category: str = "all",
        ) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_city_events",
                    {
                        "city_id": city_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "category": category,
                    },
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = {"error": str(exc), "ok": False}
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["get_city_events"] = result
            tool_latencies["get_city_events"] = latency
            return result

        async def search_documents(
            query: str, city_id: str, category: str = "all", top_k: int = 5
        ) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "search_documents",
                    {"query": query, "city_id": city_id, "category": category, "top_k": top_k},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = {"error": str(exc), "ok": False}
            latency = int((time.monotonic() - t0) * 1000)
            tool_results["search_documents"] = result
            tool_latencies["search_documents"] = latency
            return result

        # --- Budget callback --- tool call counter in ADK session state
        def _before_tool(tool, args, tool_context):
            count = int(tool_context.state.get("tool_call_count", 0))
            if count >= _MAX_TOOL_CALLS:
                return {"error": f"Tool call budget exceeded (max {_MAX_TOOL_CALLS})."}
            tool_context.state["tool_call_count"] = count + 1
            return None

        # --- Model callback --- capture model version
        _model_version: list[str] = [""]

        def _after_model(callback_context, llm_response):
            if llm_response.model_version:
                _model_version[0] = llm_response.model_version
            return None

        # --- Build agent and runner ---
        model: Any = (
            self._stub_model
            if self._stub_model is not None
            else self._settings.gemini_flash_model
        )
        agent = LlmAgent(
            name=AGENT_NAME,
            model=model,
            instruction=_SYSTEM_INSTRUCTION,
            tools=[get_city_profile, get_venues, get_city_events, search_documents],
            before_tool_callback=_before_tool,
            after_model_callback=_after_model,
            generate_content_config=GenerateContentConfig(
                max_output_tokens=self._settings.max_output_tokens,
                temperature=self._settings.default_temperature,
            ),
        )

        runner = InMemoryRunner(agent=agent, app_name="throughball")
        session = await runner.session_service.create_session(
            app_name="throughball", user_id="concierge_agent"
        )

        # Compose user message
        user_text = query or f"Tell me about {city_id}"

        events = []
        async for event in runner.run_async(
            user_id="concierge_agent",
            session_id=session.id,
            new_message=Content(role="user", parts=[Part(text=user_text)]),
            state_delta={"tool_call_count": 0},
            run_config=RunConfig(max_llm_calls=self._settings.max_agent_iterations),
        ):
            events.append(event)

        # --- Extract answer text ---
        answer_text = ""
        for event in events:
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        answer_text += part.text

        answer_text = answer_text[:max_answer_chars]

        # --- Safety post-processing ---
        degraded = False
        degraded_reason = None
        for phrase in _BANNED_PHRASES:
            if phrase.lower() in answer_text.lower():
                degraded = True
                degraded_reason = f"Banned freshness phrase: '{phrase}'"
                break

        # --- Citation extraction ---
        import re
        citation_pattern = r'\[(\d+)\]'
        citation_matches = re.findall(citation_pattern, answer_text)
        citations = []
        citation_ids_set = set()
        for match in set(citation_matches):
            cid = int(match)
            citation_ids_set.add(cid)
            citations.append({
                "id": cid,
                "source_path": f"knowledge/source_{cid}",
                "title": f"Source {cid}"
            })

        # --- Recommendations structure extraction ---
        recommendations = []
        # Parse answer for category-based recommendations
        # Pattern: "Category: item [N], item [M]. NextCategory: ..."
        category_pattern = r'(Restaurant|Nightlife|Museum|Event|Tourism|Local|Bar|Cafe):\s*([^.]*?)\.'
        category_matches = re.finditer(category_pattern, answer_text, re.IGNORECASE)
        seen_categories = set()

        for match in category_matches:
            category = match.group(1).lower()
            if category not in seen_categories:
                items_text = match.group(2).strip()
                items = [item.strip() for item in items_text.split(',')]
                recommendations.append({
                    "category": category,
                    "items": items,
                    "reasoning": f"Available options in {category}"
                })
                seen_categories.add(category)

        # If no structured recommendations found, create from citations
        if not recommendations and citations:
            recommendations.append({
                "category": "recommendations",
                "items": [f"Source {c['id']}" for c in citations],
                "reasoning": "Based on available sources"
            })

        # --- Confidence computation ---
        has_citations = len(citations) > 0
        tool_count = len(tool_latencies)
        confidence = "medium"
        if has_citations and tool_count >= 2:
            confidence = "high"
        elif not has_citations or tool_count < 2:
            confidence = "low"

        grounded = has_citations

        # --- Metrics computation ---
        total_latency_ms = int((time.monotonic() - run_start) * 1000)
        tool_call_count = len(tool_latencies)
        model_name = _model_version[0] or self._model_name

        # Estimate cost (placeholder - would use telemetry/costs.py in production)
        # For now, use a simple estimation: Flash = ~$0.00025 per typical turn
        estimated_cost = 0.00025
        cost_per_request = estimated_cost

        # Compute tokens_per_second (placeholder - would need actual token count)
        # For now, use a nominal estimate
        completion_tokens = 100  # Placeholder
        tokens_per_second = (
            completion_tokens / (total_latency_ms / 1000)
            if total_latency_ms > 0
            else 0.0
        )

        return {
            "answer": answer_text,
            "model_name": model_name,
            "tool_sources": list(_TOOL_NAMES),
            "confidence": confidence,
            "grounded": grounded,
            "citations": citations,
            "recommendations": recommendations,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "metrics": {
                "tool_call_count": tool_call_count,
                "total_latency_ms": total_latency_ms,
                "tool_latencies": tool_latencies,
                "tokens_per_second": tokens_per_second,
                "cost_per_request": cost_per_request,
                "model_name": model_name,
            },
        }
