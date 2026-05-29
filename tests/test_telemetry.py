import json
import logging

from throughball_ai.adk import AdkCallbackHooks


def test_model_call_telemetry_includes_cost_and_token_fields(caplog):
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
            latency_ms=42,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    assert event["event_type"] == "model_call_completed"
    assert event["estimated_cost"] >= 0
    assert event["prompt_tokens"] == 10
    assert event["completion_tokens"] == 5
    assert event["total_tokens"] == 15
    assert event["model_name"] == "gemini-2.0-flash-001"

    logged = json.loads(caplog.records[0].message)
    assert logged["request_id"] == "req_1"
    assert logged["model_name"] == "gemini-2.0-flash-001"
