import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from throughball_ai.mcp.context import RequestContext

logger = logging.getLogger("throughball_ai.mcp.trace")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


_new_id = new_id  # internal alias kept for backward compat


def emit_tool_call_trace(
    *,
    context: RequestContext,
    tool_name: str,
    status: str,
    source_type: Optional[str],
    cache_hit: bool,
    latency_ms: int,
    retry_count: int,
    degraded: bool,
    degraded_reason: Optional[str],
    jsonl_path: str = "telemetry/traces.jsonl",
    environment: str = "local",
    service: str = "throughball-ai",
) -> dict:
    event = {
        "event_type": "tool_call_completed",
        "event_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "service": service,
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "span_id": _new_id("sp"),
        "parent_span_id": None,
        "agent_run_id": None,
        "tool_call_id": _new_id("tc"),
        "tool_name": tool_name,
        "status": status,
        "source_type": source_type,
        "cache_hit": cache_hit,
        "latency_ms": latency_ms,
        "retry_count": retry_count,
        "degraded_mode": degraded,
        "degraded_reason": degraded_reason,
    }

    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    logger.info(line)

    os.makedirs(os.path.dirname(jsonl_path) if os.path.dirname(jsonl_path) else ".", exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    return event
