import asyncio
import pytest
from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.wrappers import execute_with_middleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_context(request_id="req_1"):
    return RequestContext(request_id=request_id, trace_id="tr_1")


async def instant_handler(**_kwargs):
    return {"ok": True, "data": "result", "source_type": "seeded"}


async def slow_handler(**_kwargs):
    await asyncio.sleep(10)
    return {"ok": True, "data": "result", "source_type": "seeded"}


class RetryableError(Exception):
    retryable = True


class NonRetryableError(Exception):
    retryable = False


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_exceeded_returns_degraded():
    ctx = make_context()
    ctx.tool_call_count = 5  # already at limit
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    assert result["ok"] is True
    assert result["telemetry"]["degraded"] is True
    assert result["telemetry"]["degraded_reason"] == "TOOL_BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_budget_not_exceeded_below_limit():
    ctx = make_context()
    ctx.tool_call_count = 4  # one slot remaining
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    assert result["ok"] is True
    assert result["telemetry"]["degraded"] is False


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_second_call_returns_cache_hit():
    ctx = make_context()
    inputs = {"match_id": "m1"}
    await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs=inputs,
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs=inputs,
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    assert result["telemetry"]["cache_hit"] is True


@pytest.mark.asyncio
async def test_first_call_is_cache_miss():
    ctx = make_context()
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    assert result["telemetry"]["cache_hit"] is False


@pytest.mark.asyncio
async def test_cache_hit_does_not_increment_call_count():
    ctx = make_context()
    inputs = {"match_id": "m1"}
    await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs=inputs,
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    count_before = ctx.tool_call_count
    await execute_with_middleware(
        tool_name="get_match_state",
        handler=instant_handler,
        inputs=inputs,
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=True,
        max_calls=5,
    )
    assert ctx.tool_call_count == count_before


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_returns_degraded():
    ctx = make_context()
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=slow_handler,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=50,
        max_retry_count=0,
        cacheable=False,
        max_calls=5,
    )
    assert result["ok"] is True
    assert result["telemetry"]["degraded"] is True
    assert result["telemetry"]["degraded_reason"] == "TIMEOUT"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retryable_error_retried_once():
    call_count = {"n": 0}

    async def flaky_then_ok(**_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RetryableError("transient")
        return {"ok": True, "data": "result", "source_type": "seeded"}

    ctx = make_context()
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=flaky_then_ok,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=False,
        max_calls=5,
    )
    assert call_count["n"] == 2
    assert result["ok"] is True
    assert result["telemetry"]["retry_count"] == 1


@pytest.mark.asyncio
async def test_non_retryable_error_not_retried():
    call_count = {"n": 0}

    async def always_fails(**_kwargs):
        call_count["n"] += 1
        raise NonRetryableError("bad input")

    ctx = make_context()
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=always_fails,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=False,
        max_calls=5,
    )
    assert call_count["n"] == 1
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_retryable_error_exhausted_returns_error():
    async def always_retryable(**_kwargs):
        raise RetryableError("always fails")

    ctx = make_context()
    result = await execute_with_middleware(
        tool_name="get_match_state",
        handler=always_retryable,
        inputs={"match_id": "m1"},
        context=ctx,
        timeout_ms=1500,
        max_retry_count=1,
        cacheable=False,
        max_calls=5,
    )
    assert result["ok"] is False
    assert result["telemetry"]["retry_count"] == 1
