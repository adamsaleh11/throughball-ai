import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from throughball_ai.telemetry.costs import estimate_model_cost

logger = logging.getLogger("throughball_ai.telemetry")


@dataclass(frozen=True)
class TelemetryContext:
    request_id: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    agent_run_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    environment: str = "local"
    service: str = "throughball-ai"


def emit_model_call_completed(
    context: TelemetryContext,
    model: str,
    latency_ms: int,
    usage: Optional[Mapping[str, Any]] = None,
    retry_count: int = 0,
    degraded_mode: bool = False,
    retrieval_count: int = 0,
    citation_count: int = 0,
) -> dict[str, Any]:
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    estimated_cost, estimator_version = estimate_model_cost(prompt_tokens, completion_tokens, model)

    event = {
        "event_type": "model_call_completed",
        "event_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": context.environment,
        "service": context.service,
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "span_id": context.span_id,
        "parent_span_id": context.parent_span_id,
        "agent_run_id": context.agent_run_id,
        "tool_call_id": context.tool_call_id,
        "model": model,
        "latency_ms": latency_ms,
        "retry_count": retry_count,
        "degraded_mode": degraded_mode,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "cost_estimator_version": estimator_version,
        "retrieval_count": retrieval_count,
        "citation_count": citation_count,
    }
    logger.info(json.dumps(event, separators=(",", ":"), sort_keys=True))
    return event
