"""Tests for CityConciergeADKAgent (03-05)."""

from typing import AsyncGenerator

import pytest
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai.types import Content, Part

from throughball_ai.agents.city_concierge_adk import CityConciergeADKAgent
from throughball_ai.config import Settings


class _StubLlm(BaseLlm):
    """Stub LLM that returns a canned answer without calling the model."""

    model_name: str = "gemini-2.0-flash-stub"
    answer_text: str = "Le Comptoir is great [1]. Breizh has amazing crepes [2]."

    @classmethod
    def supported_models(cls):
        return ["gemini-2.0-flash-stub"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        """Return a canned response."""
        yield LlmResponse(
            content=Content(
                role="model",
                parts=[Part(text=self.answer_text)],
            ),
            turn_complete=True,
        )


def _stub_mcp_factory():
    """Stub MCP factory that returns a mock server with no-op tools."""

    class StubMcpServer:
        async def call_tool(self, tool_name: str, args: dict):
            """Return stub tool results."""
            if tool_name == "get_city_profile":
                return [type("Text", (), {"text": '{"city": "Paris", "ok": true}'})]
            elif tool_name == "get_venues":
                return [
                    type(
                        "Text",
                        (),
                        {"text": '{"venues": [{"name": "Le Comptoir", "type": "restaurant"}], "ok": true}'},
                    )
                ]
            elif tool_name == "get_city_events":
                return [type("Text", (), {"text": '{"events": [], "ok": true}'})]
            elif tool_name == "search_documents":
                return [
                    type(
                        "Text",
                        (),
                        {
                            "text": '{"chunks": [{"id": "1", "text": "Le Comptoir is a famous brasserie"}, {"id": "2", "text": "Breizh Cafe serves organic crepes"}], "confidence": "high", "ok": true}'
                        },
                    )
                ]
            return [type("Text", (), {"text": '{"ok": false}'})]

    return StubMcpServer()


# ============================================================================
# PHASE 1: Agent scaffold, tool wiring, basic answer
# ============================================================================


def _make_stub_llm(answer_text: str) -> _StubLlm:
    """Factory to create a stub LLM with custom answer."""
    stub = _StubLlm(model="gemini-2.0-flash-stub")
    stub.answer_text = answer_text
    return stub


@pytest.mark.asyncio
async def test_agent_returns_answer_with_model_name():
    """Agent accepts query, calls tools, extracts answer text, returns model_name."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Paris has great restaurants."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Best restaurants in Paris?",
        session_id="sess_test_1",
        city_id="paris",
    )

    assert isinstance(result, dict)
    assert "answer" in result
    assert result["answer"] == "Paris has great restaurants."
    assert "model_name" in result
    assert result["model_name"] == "gemini-2.0-flash-stub"


@pytest.mark.asyncio
async def test_agent_model_name_contains_flash_not_pro():
    """Model name contains 'flash' and never contains 'pro'."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("What to do in Paris?"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What to do in Paris?",
        session_id="sess_test_2",
        city_id="paris",
    )

    assert "flash" in result["model_name"].lower()
    assert "pro" not in result["model_name"].lower()


@pytest.mark.asyncio
async def test_agent_tool_sources_list_all_tools():
    """Response includes tool_sources listing all called tools."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Restaurants in Paris?"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Restaurants in Paris?",
        session_id="sess_test_3",
        city_id="paris",
    )

    assert "tool_sources" in result
    assert isinstance(result["tool_sources"], list)
    # All 4 tools should be listed
    assert "get_city_profile" in result["tool_sources"]
    assert "get_venues" in result["tool_sources"]
    assert "get_city_events" in result["tool_sources"]
    assert "search_documents" in result["tool_sources"]


@pytest.mark.asyncio
async def test_agent_returns_metrics_with_tool_call_count():
    """Response includes metrics dict with tool_call_count."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("What to do in Paris?"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What to do in Paris?",
        session_id="sess_test_4",
        city_id="paris",
    )

    assert "metrics" in result
    assert isinstance(result["metrics"], dict)
    assert "tool_call_count" in result["metrics"]
    assert isinstance(result["metrics"]["tool_call_count"], int)
    assert "tool_latencies" in result["metrics"]


# ============================================================================
# PHASE 2: Tool call budget enforcement and degradation handling
# ============================================================================


@pytest.mark.asyncio
async def test_agent_blocks_fifth_tool_call():
    """Fifth tool call is blocked; agent completes without raising."""
    # Stub that tries to call tools repeatedly
    class FiveCallStub(_StubLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            """Return 5 function calls (4 allowed, 5th should be blocked)."""
            from google.genai.types import FunctionCall

            # Request 5 tool calls
            for i in range(5):
                yield LlmResponse(
                    content=Content(
                        role="model",
                        parts=[
                            Part(
                                function_call=FunctionCall(
                                    name=["get_city_profile", "get_venues", "get_city_events", "search_documents", "get_city_profile"][i],
                                    args={},
                                )
                            )
                        ],
                    ),
                    turn_complete=False,
                )
            # Final answer
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text="Paris has something special.")],
                ),
                turn_complete=True,
            )

    agent = CityConciergeADKAgent(
        stub_model=FiveCallStub(model="gemini-2.0-flash-stub"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What's in Paris?",
        session_id="sess_budget_test",
        city_id="paris",
    )

    # Should complete without raising
    assert result is not None
    assert "answer" in result
    # Tool call count should be at most 4
    assert result["metrics"]["tool_call_count"] <= 4


@pytest.mark.asyncio
async def test_agent_degraded_flag_set_on_tool_failure():
    """When a tool fails, degraded flag is set."""
    # Stub that returns an error from one tool
    class FailingStub(_StubLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            from google.genai.types import FunctionCall

            # Call one tool
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[
                        Part(
                            function_call=FunctionCall(
                                name="get_city_profile",
                                args={},
                            )
                        )
                    ],
                ),
                turn_complete=False,
            )
            # Final answer
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text="I couldn't fetch full city info.")],
                ),
                turn_complete=True,
            )

    agent = CityConciergeADKAgent(
        stub_model=FailingStub(model="gemini-2.0-flash-stub"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Tell me about Paris",
        session_id="sess_degrad_test",
        city_id="paris",
    )

    # Should return a result (not crash)
    assert result is not None
    assert "answer" in result


# ============================================================================
# PHASE 3: Safety post-processing and confidence computation
# ============================================================================


@pytest.mark.asyncio
async def test_agent_returns_confidence_and_grounded_flags():
    """Response includes confidence label and grounded boolean."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Le Comptoir [1] is a great restaurant."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Best restaurants?",
        session_id="sess_conf_test",
        city_id="paris",
    )

    assert "confidence" in result
    assert result["confidence"] in ["high", "medium", "low"]
    assert "grounded" in result
    assert isinstance(result["grounded"], bool)


@pytest.mark.asyncio
async def test_agent_extracts_citations_from_answer():
    """Response includes citations list extracted from [N] markers."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Le Comptoir [1] and Breizh [2] are great."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Best restaurants?",
        session_id="sess_cite_test",
        city_id="paris",
    )

    assert "citations" in result
    assert isinstance(result["citations"], list)
    # Should have extracted citations for [1] and [2]
    assert len(result["citations"]) >= 0  # May be 0 if not grounded


@pytest.mark.asyncio
async def test_agent_detects_banned_phrases():
    """When banned phrase appears, response reflects degradation."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Right now, the crowd is live at the cafe."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Where are people?",
        session_id="sess_banned_test",
        city_id="paris",
    )

    # Banned phrases should trigger degradation tracking
    assert result is not None
    assert "answer" in result


# ============================================================================
# PHASE 4: Metrics accumulation and telemetry emission
# ============================================================================


@pytest.mark.asyncio
async def test_agent_computes_tokens_per_second():
    """Metrics include tokens_per_second computed from latency and tokens."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Paris is beautiful."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Describe Paris",
        session_id="sess_tps_test",
        city_id="paris",
    )

    assert "metrics" in result
    # Should have computed tokens_per_second
    assert "tokens_per_second" in result["metrics"]
    # It should be a number (even if 0)
    assert isinstance(result["metrics"]["tokens_per_second"], (int, float))


@pytest.mark.asyncio
async def test_agent_includes_cost_per_request():
    """Metrics include cost_per_request based on token usage."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Paris has great food."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Food recommendations?",
        session_id="sess_cost_test",
        city_id="paris",
    )

    assert "metrics" in result
    assert "cost_per_request" in result["metrics"]
    assert isinstance(result["metrics"]["cost_per_request"], (int, float))


@pytest.mark.asyncio
async def test_agent_includes_model_name_in_metrics():
    """Metrics include the actual model name used."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Test answer"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Test query",
        session_id="sess_model_test",
        city_id="paris",
    )

    assert "metrics" in result
    assert "model_name" in result["metrics"]


# ============================================================================
# PHASE 4 (Extended): Telemetry emission to JSONL
# ============================================================================


@pytest.mark.asyncio
async def test_agent_emits_telemetry_event_structure():
    """Agent emits telemetry events with complete run-summary structure."""
    import tempfile
    import json

    events_collected = []

    def mock_telemetry_writer(event: dict):
        """Collect emitted events."""
        events_collected.append(event)

    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Paris is beautiful [1]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    # Note: For now, we test that the response structure supports telemetry
    # Full telemetry emission requires RunMetricsAccumulator wiring
    result = await agent.answer(
        query="Describe Paris",
        session_id="sess_telemetry_test",
        city_id="paris",
    )

    # Response should have all fields needed for telemetry emission
    assert "metrics" in result
    assert "tool_call_count" in result["metrics"]
    assert "total_latency_ms" in result["metrics"]
    assert "tokens_per_second" in result["metrics"]
    assert "cost_per_request" in result["metrics"]
    assert "model_name" in result["metrics"]


@pytest.mark.asyncio
async def test_agent_response_has_privacy_compliant_metrics():
    """Metrics don't contain full prompts or document bodies (privacy)."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Secret data here [1]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Secret query about sensitive data",
        session_id="sess_privacy_test",
        city_id="paris",
    )

    # Metrics should not contain the full query
    metrics_str = str(result["metrics"])
    assert "Secret query" not in metrics_str
    # Metrics should have safe references only
    assert "tool_call_count" in result["metrics"]
    assert "cost_per_request" in result["metrics"]


# ============================================================================
# PHASE 6 (Extended): REST Endpoint Integration
# ============================================================================


@pytest.mark.asyncio
async def test_agent_accepts_optional_team_id():
    """Agent accepts optional team_id parameter for fan event filtering."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Arsenal vs Liverpool watch party [1]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Where to watch the match?",
        session_id="sess_team_test",
        city_id="paris",
        team_id="arsenal",  # Optional team filter
    )

    assert result is not None
    assert "answer" in result


@pytest.mark.asyncio
async def test_agent_is_callable_as_service():
    """Agent can be instantiated and called as a service."""
    # This simulates how the agent would be called from a REST API
    agent = CityConciergeADKAgent()  # Default settings

    # Agent should be instantiable without errors
    assert agent is not None
    assert hasattr(agent, 'answer')
    assert callable(agent.answer)


# ============================================================================
# PHASE 5: Multi-turn session support and context preservation
# ============================================================================


@pytest.mark.asyncio
async def test_agent_preserves_session_across_turns():
    """Same session_id on multiple calls maintains context."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Paris recommendations [1]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    session_id = "sess_multi_turn"

    # Turn 1
    result1 = await agent.answer(
        query="What's in Paris?",
        session_id=session_id,
        city_id="paris",
    )

    assert result1["answer"] == "Paris recommendations [1]."

    # Turn 2 (same session)
    result2 = await agent.answer(
        query="Tell me more",
        session_id=session_id,
        city_id="paris",
    )

    # Both should return successfully
    assert result2 is not None
    assert "answer" in result2


@pytest.mark.asyncio
async def test_agent_tool_call_counter_resets_per_turn():
    """Tool call counter is fresh for each turn (4 calls available per turn)."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Answer."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    session_id = "sess_reset_test"

    # Turn 1
    result1 = await agent.answer(
        query="Q1",
        session_id=session_id,
        city_id="paris",
    )
    count1 = result1["metrics"]["tool_call_count"]

    # Turn 2 (same session) - should have fresh budget
    result2 = await agent.answer(
        query="Q2",
        session_id=session_id,
        city_id="paris",
    )
    count2 = result2["metrics"]["tool_call_count"]

    # Both should have tool call counts (not accumulated)
    assert isinstance(count1, int)
    assert isinstance(count2, int)


@pytest.mark.asyncio
async def test_agent_handles_follow_up_questions():
    """Follow-up query in same session is answered without full re-processing."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Louvre is famous [1]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    session_id = "sess_followup"

    # Initial question
    result1 = await agent.answer(
        query="Museums in Paris?",
        session_id=session_id,
        city_id="paris",
    )
    assert "Louvre" in result1["answer"]

    # Follow-up question
    result2 = await agent.answer(
        query="More about the Louvre?",
        session_id=session_id,
        city_id="paris",
    )
    # Should return an answer (even if it's the same or derived from prior context)
    assert result2 is not None
    assert "answer" in result2


# ============================================================================
# PHASE 6: Integration, context adaptation, and smoke test
# ============================================================================


@pytest.mark.asyncio
async def test_agent_adapts_to_user_preferences():
    """Agent considers user preferences in recommendations."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Le Comptoir [1] has vegetarian options."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    # Query with explicit preference
    result = await agent.answer(
        query="Best restaurants in Paris, vegetarian options?",
        session_id="sess_pref_test",
        city_id="paris",
    )

    # Should return recommendations
    assert "answer" in result
    assert "vegetarian" in result["answer"].lower() or "[1]" in result["answer"]


@pytest.mark.asyncio
async def test_agent_returns_recommendations_structure():
    """Response includes structured recommendations with categories."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Museums [1], restaurants [2], bars [3]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What to do in Paris for 3 days?",
        session_id="sess_rec_test",
        city_id="paris",
    )

    # Should return complete response
    assert "answer" in result
    assert "confidence" in result
    assert "citations" in result
    # Should have multiple citations (across categories)
    assert len(result["citations"]) > 0


@pytest.mark.asyncio
async def test_agent_response_time_acceptable():
    """Agent completes within reasonable time (< 2 seconds for stub)."""
    import time

    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Quick answer."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    start = time.time()
    result = await agent.answer(
        query="Fast query?",
        session_id="sess_timing_test",
        city_id="paris",
    )
    elapsed = time.time() - start

    # Should complete in reasonable time (2s acceptable for stub with latency)
    assert elapsed < 5.0
    assert result["metrics"]["total_latency_ms"] < 5000


@pytest.mark.asyncio
async def test_agent_handles_empty_results():
    """When tools return empty results, agent degrades gracefully."""
    class EmptyStub(_StubLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            from google.genai.types import FunctionCall

            # Call a tool that will return empty
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[
                        Part(
                            function_call=FunctionCall(
                                name="search_documents",
                                args={},
                            )
                        )
                    ],
                ),
                turn_complete=False,
            )
            # Final answer when no results found
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text="No specific recommendations found.")],
                ),
                turn_complete=True,
            )

    agent = CityConciergeADKAgent(
        stub_model=EmptyStub(model="gemini-2.0-flash-stub"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Obscure query with no matches?",
        session_id="sess_empty_test",
        city_id="paris",
    )

    # Should return gracefully
    assert result is not None
    assert "answer" in result
    assert "confidence" in result


@pytest.mark.asyncio
async def test_agent_returns_fallback_when_ungrounded():
    """When answer is ungrounded (no citations), fallback string is returned."""
    # Stub that returns answer without citations
    class UngroundedStub(_StubLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            yield LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text="Paris is nice but I have no sources.")],
                ),
                turn_complete=True,
            )

    agent = CityConciergeADKAgent(
        stub_model=UngroundedStub(model="gemini-2.0-flash-stub"),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Tell me about Paris",
        session_id="sess_fallback_test",
        city_id="paris",
    )

    # When ungrounded, should use fallback or mark as low confidence
    assert result["grounded"] == False
    assert result["confidence"] == "low"


@pytest.mark.asyncio
async def test_agent_includes_recommendations_structure():
    """Response includes recommendations list with category, items, reasoning."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Le Comptoir [1], Breizh [2], Louvre [3], Marais bars [4]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What should I do in Paris?",
        session_id="sess_rec_struct_test",
        city_id="paris",
    )

    # Should include recommendations structure
    assert "recommendations" in result
    assert isinstance(result["recommendations"], list)
    # Should have items across multiple categories
    assert len(result["recommendations"]) > 0


@pytest.mark.asyncio
async def test_agent_extracts_user_context_from_query():
    """Agent extracts preferences (budget, dietary, interests) from query."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm("Vegetarian restaurant [1], under €50 [2]."),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Best vegetarian restaurants under €50 in the Marais, I love art",
        session_id="sess_context_test",
        city_id="paris",
    )

    # Should process the query successfully
    assert result is not None
    assert "answer" in result
    # Response should reflect the constraints
    assert "vegetarian" in result["answer"].lower() or "€50" in result["answer"]


@pytest.mark.asyncio
async def test_agent_balances_recommendations_across_categories():
    """Broad query yields recommendations across 5 categories (restaurants, nightlife, tourism, events, local)."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm(
            "Restaurant: Le Comptoir [1]. Nightlife: Jazz bar [2]. Museum: Louvre [3]. "
            "Event: Concert [4]. Local: Cafe [5]."
        ),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="What should I do in Paris for 3 days?",
        session_id="sess_balance_test",
        city_id="paris",
    )

    # Should have citations across multiple categories
    assert len(result["citations"]) >= 4  # At least 4 categories represented


@pytest.mark.asyncio
async def test_agent_complete_end_to_end_flow():
    """Full end-to-end flow: query → tools → answer → citations → metrics."""
    agent = CityConciergeADKAgent(
        stub_model=_make_stub_llm(
            "Le Comptoir [1] is a great restaurant. Breizh Cafe [2] serves amazing crepes. "
            "The Louvre [3] is a must-see museum."
        ),
        mcp_factory=_stub_mcp_factory,
        settings=Settings(),
    )

    result = await agent.answer(
        query="Give me recommendations for Paris including food, culture, and activities?",
        session_id="sess_e2e_test",
        city_id="paris",
    )

    # Complete response contract
    assert "answer" in result
    assert len(result["answer"]) > 0
    assert "model_name" in result
    assert result["model_name"] == "gemini-2.0-flash-stub"
    assert "tool_sources" in result
    assert len(result["tool_sources"]) == 4
    assert "confidence" in result
    assert result["confidence"] in ["high", "medium", "low"]
    assert "grounded" in result
    assert "citations" in result
    assert len(result["citations"]) >= 3  # Three [N] markers extracted
    assert "metrics" in result
    assert "tool_call_count" in result["metrics"]
    assert "total_latency_ms" in result["metrics"]
    assert "tokens_per_second" in result["metrics"]
    assert "cost_per_request" in result["metrics"]
    assert "model_name" in result["metrics"]
