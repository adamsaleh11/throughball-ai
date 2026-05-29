import asyncio
import time
from typing import Callable, Optional

from throughball_ai.mcp.context import RequestContext


def _is_retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False))


def _degraded_telemetry(
    degraded_reason: str,
    cache_hit: bool = False,
    retry_count: int = 0,
    latency_ms: int = 0,
    source_type: Optional[str] = None,
) -> dict:
    return {
        "degraded": True,
        "degraded_reason": degraded_reason,
        "cache_hit": cache_hit,
        "retry_count": retry_count,
        "latency_ms": latency_ms,
        "source_type": source_type,
        "external_api_called": False,
    }


def _ok_telemetry(
    cache_hit: bool = False,
    retry_count: int = 0,
    latency_ms: int = 0,
    source_type: Optional[str] = None,
) -> dict:
    return {
        "degraded": False,
        "degraded_reason": None,
        "cache_hit": cache_hit,
        "retry_count": retry_count,
        "latency_ms": latency_ms,
        "source_type": source_type,
        "external_api_called": False,
    }


def _error_telemetry(
    retry_count: int = 0,
    latency_ms: int = 0,
) -> dict:
    return {
        "degraded": False,
        "degraded_reason": None,
        "cache_hit": False,
        "retry_count": retry_count,
        "latency_ms": latency_ms,
        "source_type": None,
        "external_api_called": False,
    }


async def execute_with_middleware(
    *,
    tool_name: str,
    handler: Callable,
    inputs: dict,
    context: RequestContext,
    timeout_ms: int,
    max_retry_count: int,
    cacheable: bool,
    max_calls: Optional[int] = None,
) -> dict:
    max_allowed_calls = context.max_tool_calls if max_calls is None else max_calls

    if context.tool_call_count >= max_allowed_calls:
        return {
            "ok": True,
            "tool": tool_name,
            "data": {},
            "source_type": "none",
            "telemetry": _degraded_telemetry(
                "TOOL_BUDGET_EXCEEDED", source_type="none"
            ),
        }

    if cacheable:
        cached = context.get_cached(tool_name, inputs)
        if cached is not None:
            result = dict(cached)
            result["telemetry"] = dict(cached.get("telemetry", {}))
            result["telemetry"]["cache_hit"] = True
            return result

    context.tool_call_count += 1

    retry_count = 0
    last_exc: Optional[BaseException] = None
    start = time.monotonic()

    while True:
        try:
            result = await asyncio.wait_for(
                handler(**inputs), timeout=timeout_ms / 1000
            )
            elapsed = int((time.monotonic() - start) * 1000)
            result = dict(result)
            source_type = result.get("source_type")
            handler_telemetry = dict(result.get("telemetry", {}))
            base_telemetry = _ok_telemetry(
                cache_hit=False,
                retry_count=retry_count,
                latency_ms=elapsed,
                source_type=source_type,
            )
            base_telemetry.update(handler_telemetry)
            base_telemetry["cache_hit"] = False
            base_telemetry["retry_count"] = retry_count
            base_telemetry["latency_ms"] = elapsed
            base_telemetry["source_type"] = source_type
            result["telemetry"] = base_telemetry
            if cacheable:
                context.set_cached(tool_name, inputs, result)
            return result

        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "ok": True,
                "tool": tool_name,
                "data": {},
                "source_type": "none",
                "telemetry": _degraded_telemetry(
                    "TIMEOUT",
                    retry_count=retry_count,
                    latency_ms=elapsed,
                    source_type="none",
                ),
            }

        except Exception as exc:
            last_exc = exc
            if _is_retryable(exc) and retry_count < max_retry_count:
                retry_count += 1
                await asyncio.sleep(0.2)
                continue
            break

    elapsed = int((time.monotonic() - start) * 1000)
    return {
        "ok": False,
        "tool": tool_name,
        "error": {"message": str(last_exc)},
        "telemetry": _error_telemetry(retry_count=retry_count, latency_ms=elapsed),
    }
