"""ADK-backed Match Analyst Agent (03-06).

Implements MatchAnalystADKAgent as a google.adk.agents.LlmAgent wrapper.
The LLM owns tool dispatch (ReAct); Python enforces the tool-call budget and
retrieval cost rules (via before_tool_callback / wrappers), runs a deterministic
groundedness self-check, separates facts from inference, assembles citations from
real tool output, computes confidence, and emits telemetry.

Flash-only by design: there is no Pro model, no escalation flag, no model routing.
This keeps per-request cost small and predictable for a side project.
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

from throughball_ai.adk.metrics import build_llm_metrics
from throughball_ai.config import Settings, get_settings
from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.trace import new_id

AGENT_NAME = "match_analyst"
_MAX_TOOL_CALLS = 4
_MAX_CHUNKS = 5
_MAX_ANSWER_CHARS = 1200
_AGENT_MAX_OUTPUT_TOKENS = 384

_TOOL_NAMES = ("get_match_state", "get_team_profile", "search_documents")

# Momentum/score vocabulary used by the self-check to decide which claims must be
# backed by a get_match_state result.
_MATCH_FACT_TERMS = (
    "score", "minute", "leads", "leading", "goal", "momentum", "winning", "losing",
)

_SYSTEM_INSTRUCTION = (
    "You are the Match Analyst for the Throughball FIFA World Cup companion app. "
    "You explain the tactical state of a match: momentum, tactical context, historical "
    "comparisons, and player/team insights.\n\n"
    "TOOLS (use the minimum needed — tool calls cost money):\n"
    "- get_match_state: ALWAYS call this first to ground score, clock, and momentum.\n"
    "- get_team_profile: call ONLY when the question needs team context, supporter, or "
    "historical-style detail.\n"
    "- search_documents: call ONLY when the question needs document-grounded historical or "
    "tactical comparison. Never call it more than once for the same query.\n\n"
    f"You have at most {_MAX_TOOL_CALLS} tool calls. Do not loop on retrieval.\n\n"
    "OUTPUT RULES:\n"
    "- Prefix every grounded factual statement with 'Fact:' — these must come from a tool.\n"
    "- Prefix every tactical/momentum interpretation with 'Inferred:' — these are your "
    "reasoning, not facts.\n"
    "- Cite documents with [N] markers (e.g. [1]) that map to retrieved search results.\n"
    "- Do not state a score, minute, or momentum claim that get_match_state did not provide.\n"
    "- Be concise."
)


class MatchAnalystADKAgent:
    """ADK LlmAgent wrapper for match analysis.

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
        query: Optional[str] = None,
        session_id: str = "",
        match_id: str,
        home_team_id: Optional[str] = None,
        away_team_id: Optional[str] = None,
        max_answer_chars: int = _MAX_ANSWER_CHARS,
    ) -> dict[str, Any]:
        run_start = time.monotonic()
        mcp = self._mcp_factory()

        # --- Per-run accumulators (fresh per call — safe for concurrent runs) ---
        tool_results: dict[str, dict] = {}
        tool_latencies: dict[str, int] = {}
        search_cache: dict[str, dict] = {}

        # --- MCP tool wrappers (FunctionTool callables) ---
        async def get_match_state(match_id: str, include_timeline: bool = True) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_match_state",
                    {"match_id": match_id, "include_timeline": include_timeline, "allow_external": False},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = _degraded_tool_result("get_match_state", exc)
            tool_latencies["get_match_state"] = int((time.monotonic() - t0) * 1000)
            tool_results["get_match_state"] = result
            return result

        async def get_team_profile(team_id: str, include_evidence: bool = True) -> dict:
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "get_team_profile",
                    {"team_id": team_id, "include_evidence": include_evidence, "allow_external": False},
                )
                result = json.loads(raw[0].text)
            except Exception as exc:
                result = _degraded_tool_result("get_team_profile", exc)
            tool_latencies["get_team_profile"] = int((time.monotonic() - t0) * 1000)
            tool_results["get_team_profile"] = result
            return result

        async def search_documents(query: str, top_k: int = _MAX_CHUNKS) -> dict:
            # Retrieval-loop guard: a repeat query returns the cached result.
            cache_key = (query or "").strip().lower()
            if cache_key in search_cache:
                return search_cache[cache_key]
            t0 = time.monotonic()
            try:
                raw = await mcp.call_tool(
                    "search_documents",
                    {"query": query, "top_k": _MAX_CHUNKS, "allow_external": False},
                )
                result = json.loads(raw[0].text)
                result = _truncate_chunks(result, _MAX_CHUNKS)
            except Exception as exc:
                result = _degraded_tool_result("search_documents", exc)
            tool_latencies["search_documents"] = int((time.monotonic() - t0) * 1000)
            tool_results["search_documents"] = result
            search_cache[cache_key] = result
            return result

        # --- Stable IDs and telemetry hooks ---
        from throughball_ai.adk.callbacks import AdkCallbackHooks  # lazy — avoids adk↔telemetry cycle

        hooks = AdkCallbackHooks()
        request_id = new_id("req")
        trace_id = new_id("tr")
        agent_run_id = new_id("ar")

        # --- Budget callback — counter in ADK session state ---
        def _before_tool(tool, args, tool_context):
            count = int(tool_context.state.get("tool_call_count", 0))
            if count >= _MAX_TOOL_CALLS:
                return {"error": f"Tool call budget exceeded (max {_MAX_TOOL_CALLS})."}
            tool_context.state["tool_call_count"] = count + 1
            return None

        # --- After-tool callback — emits tool_call_completed telemetry ---
        def _after_tool(tool, args, tool_context, tool_response):
            tool_name = tool.name
            is_degraded = (
                not tool_response.get("ok", True)
                or tool_response.get("telemetry", {}).get("degraded", False)
            )
            hooks.on_tool_completed(
                request_id=request_id,
                trace_id=trace_id,
                span_id=new_id("sp"),
                parent_span_id=agent_run_id,
                agent_run_id=agent_run_id,
                session_id=session_id,
                tool_call_id=new_id("tc"),
                tool_name=tool_name,
                status="degraded" if is_degraded else "ok",
                latency_ms=tool_latencies.get(tool_name, 0),
                degraded=is_degraded,
            )
            return None

        # --- Model callbacks — timing + usage capture ---
        _model_call_start: list[float] = [0.0]
        _model_version: list[str] = [""]
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
                request_id=request_id,
                trace_id=trace_id,
                span_id=new_id("sp"),
                parent_span_id=agent_run_id,
                agent_run_id=agent_run_id,
                session_id=session_id,
                model_name=_model_version[0] or self._model_name,
                latency_ms=model_latency,
                usage=dict(_usage),
                tool_call_count=len(tool_latencies),
            )
            return None

        # --- Build agent and runner ---
        model: Any = (
            self._stub_model if self._stub_model is not None else self._settings.gemini_flash_model
        )
        agent = LlmAgent(
            name=AGENT_NAME,
            model=model,
            instruction=_SYSTEM_INSTRUCTION,
            tools=[get_match_state, get_team_profile, search_documents],
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
            app_name="throughball", user_id="match_analyst_agent"
        )

        user_text = query or f"Analyze the current state of match {match_id}."

        events = []
        async for event in runner.run_async(
            user_id="match_analyst_agent",
            session_id=session.id,
            new_message=Content(role="user", parts=[Part(text=user_text)]),
            state_delta={"tool_call_count": 0},
            run_config=RunConfig(max_llm_calls=self._settings.max_agent_iterations),
        ):
            events.append(event)

        # --- Post-processing ---
        answer_text = _extract_answer_text(events)[:max_answer_chars]
        results_list = [tool_results[n] for n in _TOOL_NAMES if n in tool_results]

        facts = _parse_facts(answer_text, tool_results)
        inferences = _parse_inferences(answer_text)
        citations = _build_citations(answer_text, tool_results)
        self_check = _groundedness_check(answer_text, tool_results, citations)

        any_tool_degraded = any(
            r.get("telemetry", {}).get("degraded") or not r.get("ok", True)
            for r in results_list
        )
        degraded = not self_check["passed"] or any_tool_degraded
        degraded_reason = None if self_check["passed"] else self_check["reason"]
        if degraded_reason is None and any_tool_degraded:
            degraded_reason = "One or more tools returned degraded data."

        grounded = bool(citations) or _has_match_state(tool_results)
        confidence = _compute_confidence(tool_results, citations, any_tool_degraded, inferences)

        total_latency_ms = int((time.monotonic() - run_start) * 1000)
        model_name = _model_version[0] or self._model_name
        metrics = build_llm_metrics(
            model_name=model_name,
            latency_ms=total_latency_ms,
            usage=_usage,
            tool_call_count=len(tool_latencies),
            degraded=degraded,
        )
        metrics["total_latency_ms"] = total_latency_ms
        metrics["tool_latencies"] = dict(tool_latencies)

        hooks_event = hooks.on_agent_completed(
            request_id=request_id,
            trace_id=trace_id,
            span_id=new_id("sp"),
            parent_span_id=None,
            agent_run_id=agent_run_id,
            session_id=session.id,
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
            "facts": facts,
            "inferences": inferences,
            "confidence": confidence["label"],
            "confidence_details": confidence,
            "citations": citations,
            "grounded": grounded,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "self_check": self_check,
            "tool_sources": [_tool_source(r) for r in results_list],
            "model_name": model_name,
            "metrics": metrics,
        }


# ---------------------------------------------------------------------------
# Tool-result helpers
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


def _truncate_chunks(result: dict, max_chunks: int) -> dict:
    data = result.get("data") or {}
    for key in ("chunks", "source_paths", "document_titles", "similarity_scores", "results"):
        val = data.get(key)
        if isinstance(val, list) and len(val) > max_chunks:
            data[key] = val[:max_chunks]
    return result


def _tool_source(result: dict) -> dict:
    tel = result.get("telemetry", {})
    return {
        "tool": result.get("tool", "unknown"),
        "source_type": result.get("source_type") or tel.get("source_type"),
        "degraded": bool(tel.get("degraded")) or not result.get("ok", True),
        "external_api_called": bool(tel.get("external_api_called")),
    }


def _has_match_state(tool_results: dict[str, dict]) -> bool:
    r = tool_results.get("get_match_state")
    return bool(r and r.get("ok", False) and r.get("data"))


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------


def _extract_answer_text(events: list) -> str:
    for event in reversed(events):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    return part.text
    return ""


# ---------------------------------------------------------------------------
# Facts / inference parsing
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    # Split on sentence boundaries while keeping it simple and deterministic.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _parse_facts(answer: str, tool_results: dict[str, dict]) -> list[dict]:
    facts = []
    for sentence in _split_sentences(answer):
        if sentence.lower().startswith("fact:"):
            claim = sentence[len("fact:"):].strip()
            facts.append({"claim": claim, "source": _fact_source(claim, tool_results)})
    return facts


def _fact_source(claim: str, tool_results: dict[str, dict]) -> str:
    lower = claim.lower()
    if any(term in lower for term in _MATCH_FACT_TERMS) and _has_match_state(tool_results):
        return "get_match_state"
    if "[" in claim:
        return "search_documents"
    if "get_team_profile" in tool_results:
        return "get_team_profile"
    return "get_match_state"


def _parse_inferences(answer: str) -> list[dict]:
    inferences = []
    for sentence in _split_sentences(answer):
        if sentence.lower().startswith("inferred:"):
            claim = sentence[len("inferred:"):].strip()
            inferences.append({"claim": claim, "basis": "Derived from grounded match facts."})
    return inferences


# ---------------------------------------------------------------------------
# Citations — assembled only from real tool output
# ---------------------------------------------------------------------------


def _search_results(tool_results: dict[str, dict]) -> list[dict]:
    r = tool_results.get("search_documents")
    if not r or not r.get("ok", False):
        return []
    return r.get("data", {}).get("results", []) or []


def _build_citations(answer: str, tool_results: dict[str, dict]) -> list[dict]:
    results = _search_results(tool_results)
    citations: list[dict] = []
    seen: set[int] = set()
    for marker in re.findall(r"\[(\d+)\]", answer):
        n = int(marker)
        if n in seen:
            continue
        seen.add(n)
        if 1 <= n <= len(results):
            res = results[n - 1]
            citations.append({
                "id": n,
                "source_path": res.get("source_path") or res.get("document_id"),
                "title": res.get("title"),
            })
        # Out-of-range markers are intentionally not added; the self-check flags them.

    # Team-profile evidence references are citable, non-numbered sources.
    team = tool_results.get("get_team_profile")
    if team and team.get("ok", False):
        for eid in team.get("data", {}).get("evidence_ids", []) or []:
            citations.append({"id": None, "source_path": eid, "title": "Team profile evidence"})
    return citations


# ---------------------------------------------------------------------------
# Self-check (deterministic groundedness — no re-prompt loop)
# ---------------------------------------------------------------------------


def _groundedness_check(answer: str, tool_results: dict[str, dict], citations: list[dict]) -> dict:
    results = _search_results(tool_results)
    # 1) Every [N] marker must resolve to a retrieved chunk.
    for marker in re.findall(r"\[(\d+)\]", answer):
        n = int(marker)
        if not (1 <= n <= len(results)):
            return {
                "passed": False,
                "reason": f"Citation [{n}] does not resolve to any retrieved document.",
            }
    # 2) Score/minute/momentum claims must be backed by get_match_state.
    if not _has_match_state(tool_results):
        lower = answer.lower()
        for term in _MATCH_FACT_TERMS:
            if term in lower:
                return {
                    "passed": False,
                    "reason": f"Claim references '{term}' but no match state was retrieved.",
                }
    return {"passed": True, "reason": "All citations resolve and match claims are grounded."}


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def _compute_confidence(
    tool_results: dict[str, dict],
    citations: list[dict],
    any_tool_degraded: bool,
    inferences: list[dict],
) -> dict:
    contributors: list[str] = []
    downgrade_reasons: list[str] = []

    has_match = _has_match_state(tool_results)
    has_grounding = bool(citations)

    if has_match:
        contributors.append("Match state is available.")
    else:
        downgrade_reasons.append("No match state retrieved.")
    if has_grounding:
        contributors.append("Supporting documents/evidence are cited.")
    if any_tool_degraded:
        downgrade_reasons.append("One or more tools returned degraded data.")

    match_state = tool_results.get("get_match_state") or {}
    seeded = match_state.get("source_type") == "seeded"
    momentum_claimed = any(
        any(term in inf["claim"].lower() for term in ("momentum", "winning", "losing"))
        for inf in inferences
    )

    if not has_match or any_tool_degraded:
        label = "low"
    elif has_grounding:
        label = "high"
    else:
        label = "medium"

    # Seeded data caps live-momentum claims at medium — it is cached, not live.
    if label == "high" and seeded and momentum_claimed:
        label = "medium"
        downgrade_reasons.append("Momentum claims rest on seeded (cached) match data, not live.")

    return {"label": label, "contributors": contributors, "downgrade_reasons": downgrade_reasons}
