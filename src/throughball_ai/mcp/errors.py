from typing import Optional


class ToolError(Exception):
    """Base class for tool handler errors. Never retried."""
    retryable: bool = False


class RetryableToolError(ToolError):
    """Raised by a tool handler when the failure is transient and should be retried."""
    retryable: bool = True


def error_response(
    tool_name: str,
    code: str,
    message: str,
    retryable: bool = False,
    degraded_available: bool = False,
    details: Optional[dict] = None,
) -> dict:
    """Build a structured error response dict.

    trace_id and request_id are intentionally omitted so the calling server
    layer can inject the correct context IDs via setdefault().
    """
    return {
        "ok": False,
        "tool": tool_name,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "degraded_available": degraded_available,
            "details": details or {},
        },
        "telemetry": {
            "latency_ms": 0,
            "cache_hit": False,
            "source_type": None,
            "retry_count": 0,
            "degraded": False,
            "degraded_reason": None,
            "external_api_called": False,
        },
    }
