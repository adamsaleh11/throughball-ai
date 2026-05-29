import pytest
from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.schemas import MatchStateInput


def test_cache_miss_on_first_call():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    assert ctx.get_cached("get_match_state", {"match_id": "m1"}) is None


def test_cache_hit_on_second_call_with_same_inputs():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    result = {"ok": True, "data": "match"}
    ctx.set_cached("get_match_state", {"match_id": "m1"}, result)
    assert ctx.get_cached("get_match_state", {"match_id": "m1"}) is result


def test_cache_miss_on_different_inputs():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    ctx.set_cached("get_match_state", {"match_id": "m1"}, {"ok": True})
    assert ctx.get_cached("get_match_state", {"match_id": "m2"}) is None


def test_cache_miss_on_different_tool():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    ctx.set_cached("get_match_state", {"match_id": "m1"}, {"ok": True})
    assert ctx.get_cached("get_fan_hotspots", {"match_id": "m1"}) is None


def test_cache_scoped_to_context_instance():
    ctx1 = RequestContext(request_id="req_1", trace_id="tr_1")
    ctx2 = RequestContext(request_id="req_2", trace_id="tr_2")
    ctx1.set_cached("get_match_state", {"match_id": "m1"}, {"ok": True})
    assert ctx2.get_cached("get_match_state", {"match_id": "m1"}) is None


def test_tool_call_count_starts_at_zero():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    assert ctx.tool_call_count == 0


def test_request_context_carries_budget_and_external_policy():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1", max_tool_calls=3)
    assert ctx.max_tool_calls == 3
    assert ctx.allow_external is False


def test_tool_call_count_increments():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    ctx.tool_call_count += 1
    ctx.tool_call_count += 1
    assert ctx.tool_call_count == 2


def test_cache_key_normalizes_validated_schema_defaults():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1")
    validated = MatchStateInput(match_id="m1").model_dump()
    ctx.set_cached("get_match_state", validated, {"ok": True})
    assert ctx.get_cached("get_match_state", {"match_id": "m1"}) is not None
