from typing import Any, Optional
import uuid


def error_response(
    tool_name: str,
    code: str,
    message: str,
    retryable: bool = False,
    degraded_available: bool = False,
    details: Optional[dict] = None,
) -> dict:
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
            "trace_id": f"tr_{uuid.uuid4().hex[:12]}",
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "latency_ms": 0,
            "cache_hit": False,
            "source_type": None,
            "retry_count": 0,
            "degraded": False,
            "external_api_called": False,
        },
    }
