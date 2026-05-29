import pytest

from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.middleware import execute_with_middleware


async def instant_handler(**_kwargs):
    return {"ok": True, "data": {}, "source_type": "seeded"}


@pytest.mark.asyncio
async def test_middleware_uses_context_budget_when_max_calls_not_passed():
    ctx = RequestContext(request_id="req_1", trace_id="tr_1", max_tool_calls=1)

    first = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=False,
    )
    second = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs={"match_id": "m2"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=False,
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["telemetry"]["degraded"] is True
    assert second["telemetry"]["degraded_reason"] == "TOOL_BUDGET_EXCEEDED"
