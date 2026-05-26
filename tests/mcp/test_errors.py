"""Boundary tests for the error response contract and exception hierarchy."""
import json
import pytest
from throughball_ai.mcp.errors import (
    ToolError,
    RetryableToolError,
    error_response,
)
from throughball_ai.mcp.server import build_mcp_server


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

def test_tool_error_not_retryable():
    assert ToolError.retryable is False


def test_retryable_tool_error_is_retryable():
    assert RetryableToolError.retryable is True


def test_retryable_tool_error_is_subclass_of_tool_error():
    assert issubclass(RetryableToolError, ToolError)


# ---------------------------------------------------------------------------
# error_response dict shape
# ---------------------------------------------------------------------------

def test_error_response_ok_is_false():
    resp = error_response("my_tool", code="OOPS", message="something broke")
    assert resp["ok"] is False


def test_error_response_tool_name_present():
    resp = error_response("my_tool", code="OOPS", message="something broke")
    assert resp["tool"] == "my_tool"


def test_error_response_error_block_fields():
    resp = error_response(
        "my_tool",
        code="INVALID_INPUT",
        message="field missing",
        retryable=False,
        degraded_available=False,
        details={"field": "match_id"},
    )
    e = resp["error"]
    assert e["code"] == "INVALID_INPUT"
    assert e["message"] == "field missing"
    assert e["retryable"] is False
    assert e["degraded_available"] is False
    assert e["details"] == {"field": "match_id"}


def test_error_response_telemetry_has_no_trace_or_request_id():
    """error_response must not generate its own IDs — the server layer injects them."""
    resp = error_response("my_tool", code="ERR", message="x")
    t = resp["telemetry"]
    assert "trace_id" not in t
    assert "request_id" not in t


def test_error_response_telemetry_baseline_values():
    resp = error_response("my_tool", code="ERR", message="x")
    t = resp["telemetry"]
    assert t["latency_ms"] == 0
    assert t["cache_hit"] is False
    assert t["source_type"] is None
    assert t["retry_count"] == 0
    assert t["degraded"] is False
    assert t["external_api_called"] is False


# ---------------------------------------------------------------------------
# End-to-end: error response IDs come from the request context
# ---------------------------------------------------------------------------

async def call(mcp, tool_name: str, args: dict) -> dict:
    result = await mcp.call_tool(tool_name, args)
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_error_telemetry_ids_match_request_context():
    """trace_id and request_id in an error response must carry the request context,
    not orphaned IDs generated inside the handler."""
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {})  # missing match_id → INVALID_INPUT

    assert resp["ok"] is False
    t = resp["telemetry"]
    assert t["trace_id"].startswith("tr_"), f"bad trace_id: {t['trace_id']}"
    assert t["request_id"].startswith("req_"), f"bad request_id: {t['request_id']}"
    # Both IDs must be 16 hex chars after the prefix
    assert len(t["trace_id"]) == len("tr_") + 16
    assert len(t["request_id"]) == len("req_") + 16


@pytest.mark.asyncio
async def test_error_telemetry_id_length_is_consistent_with_ok_response():
    """ID format must be identical whether the response is ok or an error."""
    mcp = build_mcp_server()
    ok_resp = await call(mcp, "get_match_state", {"match_id": "m1"})
    err_resp = await call(mcp, "get_match_state", {})

    ok_tr = ok_resp["telemetry"]["trace_id"]
    err_tr = err_resp["telemetry"]["trace_id"]
    assert len(ok_tr) == len(err_tr), f"trace_id length mismatch: {ok_tr!r} vs {err_tr!r}"
