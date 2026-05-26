import json
import logging

from throughball_ai.telemetry import TelemetryContext, emit_model_call_completed


def test_model_call_telemetry_includes_cost_and_token_fields(caplog):
    context = TelemetryContext(
        request_id="req_1",
        trace_id="tr_1",
        span_id="sp_model_1",
        parent_span_id="sp_agent_1",
        agent_run_id="ar_1",
    )

    with caplog.at_level(logging.INFO, logger="throughball_ai.telemetry"):
        event = emit_model_call_completed(
            context=context,
            model="gemini-2.0-flash-001",
            latency_ms=42,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    assert event["event_type"] == "model_call_completed"
    assert event["estimated_cost"] >= 0
    assert event["prompt_tokens"] == 10
    assert event["completion_tokens"] == 5
    assert event["total_tokens"] == 15
    assert event["cost_estimator_version"]

    logged = json.loads(caplog.records[0].message)
    assert logged["request_id"] == "req_1"
    assert logged["model"] == "gemini-2.0-flash-001"
