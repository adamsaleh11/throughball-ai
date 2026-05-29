import pytest

from throughball_ai.telemetry import RunMetricsAccumulator


def _make_accumulator(writer=None):
    return RunMetricsAccumulator(
        agent_run_id="ar_test",
        session_id="sess_test",
        trace_id="tr_test",
        request_id="req_test",
        agent_name="fan_gathering",
        writer=writer or (lambda _event: None),
    )


# ---------------------------------------------------------------------------
# Tracer bullet: finalize emits all required fields
# ---------------------------------------------------------------------------


def test_finalize_emits_complete_run_summary():
    captured = []
    acc = _make_accumulator(writer=captured.append)

    acc.record_tool_call("get_fan_hotspots", latency_ms=120)
    acc.record_tool_call("get_city_events", latency_ms=90)
    acc.record_model_call(
        usage={"prompt_tokens": 500, "completion_tokens": 100},
        latency_ms=400,
        model_name="gemini-2.0-flash-001",
    )

    event = acc.finalize(final_confidence="high", total_latency_ms=650)

    assert event["event_type"] == "agent_run_completed"
    assert event["agent_run_id"] == "ar_test"
    assert event["session_id"] == "sess_test"
    assert event["trace_id"] == "tr_test"
    assert event["request_id"] == "req_test"
    assert event["agent_name"] == "fan_gathering"
    assert event["model_name"] == "gemini-2.0-flash-001"
    assert event["prompt_tokens"] == 500
    assert event["completion_tokens"] == 100
    assert event["total_tokens"] == 600
    assert event["tool_call_count"] == 2
    assert event["tool_latencies"] == {"get_fan_hotspots": 120, "get_city_events": 90}
    assert event["final_confidence"] == "high"
    assert event["latency_ms"] == 650
    assert event["degraded"] is False
    assert event["retries"] == 0
    assert "estimated_cost" in event
    assert "cost_per_request" in event
    assert "tokens_per_second" in event
    assert len(captured) == 1
    assert captured[0] is event


# ---------------------------------------------------------------------------
# tokens_per_second edge cases
# ---------------------------------------------------------------------------


def test_tokens_per_second_is_correct_when_both_present():
    acc = _make_accumulator()
    acc.record_model_call(
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        latency_ms=1000,
        model_name="gemini-2.0-flash-001",
    )
    event = acc.finalize(total_latency_ms=1000)
    assert event["tokens_per_second"] == 200.0


def test_tokens_per_second_is_zero_when_latency_is_zero():
    acc = _make_accumulator()
    acc.record_model_call(
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        latency_ms=0,
        model_name="gemini-2.0-flash-001",
    )
    event = acc.finalize(total_latency_ms=0)
    assert event["tokens_per_second"] == 0.0


def test_tokens_per_second_is_zero_when_no_completion_tokens():
    acc = _make_accumulator()
    acc.record_model_call(
        usage={"prompt_tokens": 100, "completion_tokens": 0},
        latency_ms=500,
        model_name="gemini-2.0-flash-001",
    )
    event = acc.finalize(total_latency_ms=500)
    assert event["tokens_per_second"] == 0.0


# ---------------------------------------------------------------------------
# tool_latencies aggregation
# ---------------------------------------------------------------------------


def test_tool_latencies_sums_when_same_tool_called_multiple_times():
    acc = _make_accumulator()
    acc.record_tool_call("get_fan_hotspots", latency_ms=100)
    acc.record_tool_call("get_fan_hotspots", latency_ms=80)
    acc.record_tool_call("get_city_events", latency_ms=60)
    event = acc.finalize(total_latency_ms=300)
    assert event["tool_latencies"] == {"get_fan_hotspots": 180, "get_city_events": 60}
    assert event["tool_call_count"] == 3


# ---------------------------------------------------------------------------
# degraded propagation
# ---------------------------------------------------------------------------


def test_degraded_is_true_when_any_tool_call_is_degraded():
    acc = _make_accumulator()
    acc.record_tool_call("get_fan_hotspots", latency_ms=100, degraded=False)
    acc.record_tool_call("get_city_events", latency_ms=90, degraded=True)
    event = acc.finalize(total_latency_ms=200)
    assert event["degraded"] is True


def test_degraded_is_false_when_no_tool_calls_are_degraded():
    acc = _make_accumulator()
    acc.record_tool_call("get_fan_hotspots", latency_ms=100, degraded=False)
    event = acc.finalize(total_latency_ms=100)
    assert event["degraded"] is False


# ---------------------------------------------------------------------------
# cost fields
# ---------------------------------------------------------------------------


def test_cost_per_request_equals_estimated_cost():
    acc = _make_accumulator()
    acc.record_model_call(
        usage={"prompt_tokens": 1000, "completion_tokens": 200},
        latency_ms=500,
        model_name="gemini-2.0-flash-001",
    )
    event = acc.finalize(total_latency_ms=500)
    assert event["cost_per_request"] == event["estimated_cost"]
    assert event["estimated_cost"] > 0


def test_unknown_model_produces_zero_cost_without_error():
    acc = _make_accumulator()
    acc.record_model_call(
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        latency_ms=300,
        model_name="some-unknown-model",
    )
    event = acc.finalize(total_latency_ms=300)
    assert event["estimated_cost"] == 0.0
    assert event["cost_per_request"] == 0.0


# ---------------------------------------------------------------------------
# privacy: no raw text in emitted event
# ---------------------------------------------------------------------------


def test_finalize_event_contains_no_raw_prompt_or_document_text():
    acc = _make_accumulator()
    acc.record_tool_call("get_fan_hotspots", latency_ms=100)
    event = acc.finalize(total_latency_ms=100)
    event_str = str(event)
    assert "user query text" not in event_str
    assert "full document body" not in event_str


# ---------------------------------------------------------------------------
# final_confidence is optional
# ---------------------------------------------------------------------------


def test_final_confidence_is_none_when_not_provided():
    acc = _make_accumulator()
    event = acc.finalize(total_latency_ms=0)
    assert event["final_confidence"] is None


# ---------------------------------------------------------------------------
# accumulator is importable from telemetry package
# ---------------------------------------------------------------------------


def test_run_metrics_accumulator_importable_from_telemetry():
    from throughball_ai.telemetry import RunMetricsAccumulator as RMA  # noqa: F401

    assert RMA is RunMetricsAccumulator
