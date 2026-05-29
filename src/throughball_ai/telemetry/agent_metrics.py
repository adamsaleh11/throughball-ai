import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger("throughball_ai.telemetry.agent_metrics")

_DEFAULT_JSONL_PATH = "telemetry/agent_runs.jsonl"


def _default_writer(event: dict[str, Any]) -> None:
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    logger.info(line)
    os.makedirs(
        os.path.dirname(_DEFAULT_JSONL_PATH) if os.path.dirname(_DEFAULT_JSONL_PATH) else ".",
        exist_ok=True,
    )
    with open(_DEFAULT_JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class RunMetricsAccumulator:
    def __init__(
        self,
        *,
        agent_run_id: str,
        session_id: str,
        trace_id: str,
        request_id: str,
        agent_name: str,
        writer: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self._agent_run_id = agent_run_id
        self._session_id = session_id
        self._trace_id = trace_id
        self._request_id = request_id
        self._agent_name = agent_name
        self._writer = writer if writer is not None else _default_writer

        self._tool_latencies: dict[str, int] = defaultdict(int)
        self._tool_call_count = 0
        self._degraded = False
        self._retries = 0

        self._model_name: Optional[str] = None
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._model_latency_ms = 0

    def record_tool_call(
        self,
        name: str,
        latency_ms: int,
        degraded: bool = False,
        retry_count: int = 0,
    ) -> None:
        self._tool_latencies[name] += latency_ms
        self._tool_call_count += 1
        self._retries += retry_count
        if degraded:
            self._degraded = True

    def record_model_call(
        self,
        usage: Mapping[str, Any],
        latency_ms: int,
        model_name: str,
    ) -> None:
        self._model_name = model_name
        self._model_latency_ms = latency_ms
        usage = usage or {}
        self._prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self._completion_tokens += int(usage.get("completion_tokens") or 0)
        self._total_tokens = self._prompt_tokens + self._completion_tokens

    def finalize(
        self,
        final_confidence: Optional[str] = None,
        total_latency_ms: int = 0,
        self_check_passed: Optional[bool] = None,
    ) -> dict[str, Any]:
        from throughball_ai.adk.metrics import build_llm_metrics  # lazy — breaks adk↔telemetry cycle
        model_name = self._model_name or "unknown"
        metrics = build_llm_metrics(
            model_name=model_name,
            latency_ms=self._model_latency_ms,
            usage={
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
            },
        )

        event: dict[str, Any] = {
            "event_type": "agent_run_completed",
            "event_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "agent_run_id": self._agent_run_id,
            "session_id": self._session_id,
            "trace_id": self._trace_id,
            "request_id": self._request_id,
            "agent_name": self._agent_name,
            "model_name": model_name,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._total_tokens,
            "tokens_per_second": metrics["tokens_per_second"],
            "estimated_cost": metrics["estimated_cost"],
            "cost_per_request": metrics["estimated_cost"],
            "tool_call_count": self._tool_call_count,
            "tool_latencies": dict(self._tool_latencies),
            "retries": self._retries,
            "degraded": self._degraded,
            "final_confidence": final_confidence,
            "latency_ms": total_latency_ms,
            "self_check_passed": self_check_passed,
        }

        self._writer(event)
        return event
