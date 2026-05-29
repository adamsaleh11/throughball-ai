from typing import Any, Mapping, Optional

from throughball_ai.telemetry.costs import estimate_model_cost


def build_llm_metrics(
    *,
    model_name: str,
    latency_ms: int = 0,
    usage: Optional[Mapping[str, Any]] = None,
    tool_call_count: int = 0,
    retry_count: int = 0,
    degraded: bool = False,
) -> dict[str, Any]:
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    estimated_cost, _estimator_version = estimate_model_cost(
        prompt_tokens,
        completion_tokens,
        model_name,
    )
    tokens_per_second = 0.0
    if latency_ms > 0 and completion_tokens > 0:
        tokens_per_second = round(completion_tokens / (latency_ms / 1000), 2)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tokens_per_second": tokens_per_second,
        "latency_ms": latency_ms,
        "estimated_cost": estimated_cost,
        "cost_per_request": estimated_cost,
        "model_name": model_name,
        "tool_call_count": tool_call_count,
        "retry_count": retry_count,
        "degraded": degraded,
    }
