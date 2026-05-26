import json
import os
import tempfile
import pytest
from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.trace import emit_tool_call_trace

REQUIRED_FIELDS = {
    "event_type",
    "event_version",
    "timestamp",
    "environment",
    "service",
    "request_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "agent_run_id",
    "tool_call_id",
    "tool_name",
    "status",
    "source_type",
    "cache_hit",
    "latency_ms",
    "retry_count",
    "degraded_mode",
    "degraded_reason",
}


def test_trace_event_has_required_fields(tmp_path):
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    log_file = tmp_path / "traces.jsonl"

    emit_tool_call_trace(
        context=ctx,
        tool_name="get_match_state",
        status="ok",
        source_type="seeded",
        cache_hit=False,
        latency_ms=42,
        retry_count=0,
        degraded=False,
        degraded_reason=None,
        jsonl_path=str(log_file),
    )

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    missing = REQUIRED_FIELDS - set(event.keys())
    assert not missing, f"Missing fields: {missing}"


def test_trace_event_type_is_tool_call_completed(tmp_path):
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    log_file = tmp_path / "traces.jsonl"
    emit_tool_call_trace(
        context=ctx,
        tool_name="get_match_state",
        status="ok",
        source_type="seeded",
        cache_hit=False,
        latency_ms=10,
        retry_count=0,
        degraded=False,
        degraded_reason=None,
        jsonl_path=str(log_file),
    )
    event = json.loads(log_file.read_text().strip())
    assert event["event_type"] == "tool_call_completed"
    assert event["event_version"] == "1.0"


def test_trace_ids_use_prefixed_format(tmp_path):
    ctx = RequestContext(request_id="req_abc", trace_id="tr_abc")
    log_file = tmp_path / "traces.jsonl"
    emit_tool_call_trace(
        context=ctx,
        tool_name="get_match_state",
        status="ok",
        source_type="seeded",
        cache_hit=False,
        latency_ms=10,
        retry_count=0,
        degraded=False,
        degraded_reason=None,
        jsonl_path=str(log_file),
    )
    event = json.loads(log_file.read_text().strip())
    assert event["request_id"] == "req_abc"
    assert event["trace_id"] == "tr_abc"
    assert event["span_id"].startswith("sp_")
    assert event["tool_call_id"].startswith("tc_")


def test_trace_appends_multiple_entries(tmp_path):
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    log_file = tmp_path / "traces.jsonl"
    for _ in range(3):
        emit_tool_call_trace(
            context=ctx,
            tool_name="get_match_state",
            status="ok",
            source_type="seeded",
            cache_hit=False,
            latency_ms=10,
            retry_count=0,
            degraded=False,
            degraded_reason=None,
            jsonl_path=str(log_file),
        )
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 3


def test_trace_degraded_fields_recorded(tmp_path):
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    log_file = tmp_path / "traces.jsonl"
    emit_tool_call_trace(
        context=ctx,
        tool_name="get_match_state",
        status="degraded",
        source_type=None,
        cache_hit=False,
        latency_ms=1500,
        retry_count=0,
        degraded=True,
        degraded_reason="TIMEOUT",
        jsonl_path=str(log_file),
    )
    event = json.loads(log_file.read_text().strip())
    assert event["degraded_mode"] is True
    assert event["degraded_reason"] == "TIMEOUT"
    assert event["status"] == "degraded"
