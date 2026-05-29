import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from throughball_ai.adk.metrics import build_llm_metrics

logger = logging.getLogger("throughball_ai.adk.callbacks")


class AdkCallbackHooks:
    def on_agent_completed(
        self,
        *,
        request_id: str,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        agent_run_id: Optional[str],
        session_id: str,
        agent_name: str,
        latency_ms: int,
        retry_count: int = 0,
        degraded: bool = False,
        final_confidence: Optional[str] = None,
        tool_latencies: Optional[dict[str, int]] = None,
        **_ignored_payloads: Any,
    ) -> dict[str, Any]:
        event = _base_event(
            event_type="agent_run_completed",
            request_id=request_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_run_id=agent_run_id,
            session_id=session_id,
            tool_call_id=None,
            latency_ms=latency_ms,
            retry_count=retry_count,
            degraded=degraded,
        )
        event["agent_name"] = agent_name
        event["final_confidence"] = final_confidence
        event["tool_latencies"] = tool_latencies or {}
        _emit(event)
        return event

    def on_model_completed(
        self,
        *,
        request_id: str,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        agent_run_id: Optional[str],
        session_id: str,
        model_name: str,
        latency_ms: int,
        usage: Optional[Mapping[str, Any]] = None,
        tool_call_count: int = 0,
        retry_count: int = 0,
        degraded: bool = False,
        **_ignored_payloads: Any,
    ) -> dict[str, Any]:
        metrics = build_llm_metrics(
            model_name=model_name,
            latency_ms=latency_ms,
            usage=usage,
            tool_call_count=tool_call_count,
            retry_count=retry_count,
            degraded=degraded,
        )
        event = {
            **_base_event(
                event_type="model_call_completed",
                request_id=request_id,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                agent_run_id=agent_run_id,
                session_id=session_id,
                tool_call_id=None,
                latency_ms=latency_ms,
                retry_count=retry_count,
                degraded=degraded,
            ),
            **metrics,
        }
        _emit(event)
        return event

    def on_tool_completed(
        self,
        *,
        request_id: str,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        agent_run_id: Optional[str],
        session_id: str,
        tool_call_id: Optional[str],
        tool_name: str,
        status: str,
        latency_ms: int,
        retry_count: int = 0,
        degraded: bool = False,
        tool_call_count: int = 0,
        **_ignored_payloads: Any,
    ) -> dict[str, Any]:
        event = _base_event(
            event_type="tool_call_completed",
            request_id=request_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_run_id=agent_run_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            latency_ms=latency_ms,
            retry_count=retry_count,
            degraded=degraded,
        )
        event.update(
            {
                "tool_name": tool_name,
                "status": status,
                "tool_call_count": tool_call_count,
            }
        )
        _emit(event)
        return event


def _base_event(
    *,
    event_type: str,
    request_id: str,
    trace_id: str,
    span_id: str,
    parent_span_id: Optional[str],
    agent_run_id: Optional[str],
    session_id: str,
    tool_call_id: Optional[str],
    latency_ms: int,
    retry_count: int,
    degraded: bool,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "event_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "agent_run_id": agent_run_id,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "latency_ms": latency_ms,
        "retry_count": retry_count,
        "degraded_mode": degraded,
    }


def _emit(event: Mapping[str, Any]) -> None:
    logger.info(json.dumps(event, separators=(",", ":"), sort_keys=True))
