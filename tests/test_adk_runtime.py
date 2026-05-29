import json
import logging

from throughball_ai.config import Settings


def test_adk_runtime_initializes_locally_from_settings():
    from throughball_ai.adk import create_runtime

    settings = Settings(
        ENVIRONMENT="local",
        SERVICE_NAME="throughball-ai",
        GEMINI_FLASH_MODEL="gemini-2.0-flash-001",
        MAX_OUTPUT_TOKENS=384,
        DEFAULT_TEMPERATURE=0.1,
        MAX_AGENT_ITERATIONS=4,
        GOOGLE_CLOUD_PROJECT=None,
        GOOGLE_CLOUD_LOCATION=None,
    )

    runtime = create_runtime(settings=settings)

    assert runtime.service == "throughball-ai"
    assert runtime.environment == "local"
    assert runtime.default_model == "gemini-2.0-flash-001"
    assert runtime.max_iterations == 4
    assert runtime.vertex_ai_configured is False


def test_adk_model_config_uses_flash_and_agent_iteration_override():
    from throughball_ai.adk import create_model_config

    settings = Settings(
        GEMINI_FLASH_MODEL="gemini-2.0-flash-001",
        MAX_OUTPUT_TOKENS=256,
        DEFAULT_TEMPERATURE=0.15,
        MAX_AGENT_ITERATIONS=3,
    )

    config = create_model_config(
        agent_name="match_analyst",
        settings=settings,
        max_iterations=5,
    )

    assert config.agent_name == "match_analyst"
    assert config.model_name == "gemini-2.0-flash-001"
    assert config.max_output_tokens == 256
    assert config.temperature == 0.15
    assert config.max_iterations == 5
    assert config.gemini_pro_enabled is False


def test_session_service_keeps_compact_state_and_rejects_full_documents():
    from throughball_ai.adk import create_session_service

    service = create_session_service()
    session = service.create_session(
        session_id="sess_1",
        request_id="req_1",
        agent_name="match_analyst",
        selected_model="gemini-2.0-flash-001",
    )

    service.update_task_state("sess_1", {"intent": "explain_momentum"})
    service.add_summary("sess_1", "Argentina pressure increased after substitutions.")
    service.add_retrieval_reference(
        "sess_1",
        {
            "document_id": "doc_1",
            "chunk_id": "chunk_1",
            "source_path": "knowledge/match.md",
            "summary": "Short evidence summary.",
            "content": "full retrieved document text must not be stored",
        },
    )
    service.increment_iteration("sess_1")
    service.increment_tool_calls("sess_1", 2)
    service.mark_degraded("sess_1")

    stored = service.get_session(session.session_id)

    assert stored.task_state == {"intent": "explain_momentum"}
    assert stored.summary == "Argentina pressure increased after substitutions."
    assert stored.iteration_count == 1
    assert stored.tool_call_count == 2
    assert stored.degraded is True
    assert stored.retrieval_refs == [
        {
            "document_id": "doc_1",
            "chunk_id": "chunk_1",
            "source_path": "knowledge/match.md",
            "summary": "Short evidence summary.",
        }
    ]


def test_llm_metrics_include_cost_and_zero_safe_derived_fields():
    from throughball_ai.adk import build_llm_metrics

    metrics = build_llm_metrics(
        model_name="gemini-2.0-flash-001",
        latency_ms=500,
        usage={"prompt_tokens": 1000, "completion_tokens": 250},
        tool_call_count=3,
        retry_count=1,
        degraded=True,
    )

    assert metrics["prompt_tokens"] == 1000
    assert metrics["completion_tokens"] == 250
    assert metrics["total_tokens"] == 1250
    assert metrics["tokens_per_second"] == 500.0
    assert metrics["latency_ms"] == 500
    assert metrics["estimated_cost"] > 0
    assert metrics["cost_per_request"] == metrics["estimated_cost"]
    assert metrics["model_name"] == "gemini-2.0-flash-001"
    assert metrics["tool_call_count"] == 3
    assert metrics["retry_count"] == 1
    assert metrics["degraded"] is True

    defaults = build_llm_metrics(model_name="gemini-2.0-flash-001")

    assert defaults["prompt_tokens"] == 0
    assert defaults["completion_tokens"] == 0
    assert defaults["total_tokens"] == 0
    assert defaults["tokens_per_second"] == 0.0
    assert defaults["cost_per_request"] == 0.0


def test_callback_hooks_emit_compact_model_telemetry(caplog):
    from throughball_ai.adk import AdkCallbackHooks

    hooks = AdkCallbackHooks()

    with caplog.at_level(logging.INFO, logger="throughball_ai.adk.callbacks"):
        event = hooks.on_model_completed(
            request_id="req_1",
            trace_id="tr_1",
            span_id="sp_model_1",
            parent_span_id="sp_agent_1",
            agent_run_id="ar_1",
            session_id="sess_1",
            model_name="gemini-2.0-flash-001",
            latency_ms=250,
            usage={"prompt_tokens": 20, "completion_tokens": 10},
            tool_call_count=2,
            retry_count=1,
            degraded=False,
            prompt="do not log this prompt",
            completion="do not log this completion",
        )

    assert event["event_type"] == "model_call_completed"
    assert event["request_id"] == "req_1"
    assert event["session_id"] == "sess_1"
    assert event["model_name"] == "gemini-2.0-flash-001"
    assert event["prompt_tokens"] == 20
    assert event["completion_tokens"] == 10
    assert event["tool_call_count"] == 2
    assert event["retry_count"] == 1
    assert event["degraded"] is False
    assert "prompt" not in event
    assert "completion" not in event

    logged = json.loads(caplog.records[0].message)
    assert "do not log this prompt" not in caplog.records[0].message
    assert logged["span_id"] == "sp_model_1"
    assert logged["session_id"] == "sess_1"


def test_callback_hooks_emit_agent_and_tool_lifecycle_events():
    from throughball_ai.adk import AdkCallbackHooks

    hooks = AdkCallbackHooks()

    agent_event = hooks.on_agent_completed(
        request_id="req_1",
        trace_id="tr_1",
        span_id="sp_agent_1",
        parent_span_id=None,
        agent_run_id="ar_1",
        session_id="sess_1",
        agent_name="match_analyst",
        latency_ms=100,
        retry_count=0,
        degraded=False,
    )
    tool_event = hooks.on_tool_completed(
        request_id="req_1",
        trace_id="tr_1",
        span_id="sp_tool_1",
        parent_span_id="sp_agent_1",
        agent_run_id="ar_1",
        session_id="sess_1",
        tool_call_id="tc_1",
        tool_name="search_documents",
        status="degraded",
        latency_ms=75,
        retry_count=1,
        degraded=True,
        tool_call_count=1,
    )

    assert agent_event["event_type"] == "agent_run_completed"
    assert agent_event["session_id"] == "sess_1"
    assert agent_event["agent_name"] == "match_analyst"
    assert agent_event["latency_ms"] == 100
    assert agent_event["degraded_mode"] is False
    assert tool_event["event_type"] == "tool_call_completed"
    assert tool_event["session_id"] == "sess_1"
    assert tool_event["tool_name"] == "search_documents"
    assert tool_event["status"] == "degraded"
    assert tool_event["tool_call_count"] == 1
    assert tool_event["degraded_mode"] is True


def test_agent_completed_hook_includes_final_confidence_and_tool_latencies():
    from throughball_ai.adk import AdkCallbackHooks

    hooks = AdkCallbackHooks()

    event = hooks.on_agent_completed(
        request_id="req_2",
        trace_id="tr_2",
        span_id="sp_agent_2",
        parent_span_id=None,
        agent_run_id="ar_2",
        session_id="sess_2",
        agent_name="fan_gathering",
        latency_ms=300,
        retry_count=0,
        degraded=False,
        final_confidence="high",
        tool_latencies={"get_fan_hotspots": 120, "get_city_events": 90},
    )

    assert event["final_confidence"] == "high"
    assert event["tool_latencies"] == {"get_fan_hotspots": 120, "get_city_events": 90}
    assert event["session_id"] == "sess_2"
