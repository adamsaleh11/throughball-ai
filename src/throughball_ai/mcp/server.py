import inspect
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.settings import MCPSettings
from throughball_ai.mcp.trace import emit_tool_call_trace
from throughball_ai.mcp.wrappers import execute_with_middleware
from throughball_ai.mcp.tools import get_match_state, get_fan_hotspots, search_documents


def _build_registry() -> dict[str, ToolDefinition]:
    return {
        "get_match_state": ToolDefinition(
            name="get_match_state",
            handler=get_match_state.handler,
            timeout_ms=get_match_state.TIMEOUT_MS,
            cacheable=True,
            max_retry_count=1,
            description="Returns current or cached match status, score, clock, and basic momentum inputs.",
        ),
        "get_fan_hotspots": ToolDefinition(
            name="get_fan_hotspots",
            handler=get_fan_hotspots.handler,
            timeout_ms=get_fan_hotspots.TIMEOUT_MS,
            cacheable=True,
            max_retry_count=1,
            description="Returns backend-computed supporter hotspot candidates and evidence.",
        ),
        "search_documents": ToolDefinition(
            name="search_documents",
            handler=search_documents.handler,
            timeout_ms=search_documents.TIMEOUT_MS,
            cacheable=True,
            max_retry_count=1,
            description="Searches retrieved evidence documents for agent synthesis.",
        ),
    }


def build_mcp_server(settings: MCPSettings | None = None) -> FastMCP:
    if settings is None:
        settings = MCPSettings()

    registry = _build_registry()
    mcp = FastMCP("throughball-ai")

    for tool_name, tool_def in registry.items():
        _register_tool(mcp, tool_def, settings)

    return mcp


def _register_tool(mcp: FastMCP, tool_def: ToolDefinition, settings: MCPSettings) -> None:
    async def wrapped(**kwargs: Any) -> dict:
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        trace_id = f"tr_{uuid.uuid4().hex[:16]}"
        ctx = RequestContext(request_id=request_id, trace_id=trace_id)

        result = await execute_with_middleware(
            tool_name=tool_def.name,
            handler=tool_def.handler,
            inputs=kwargs,
            context=ctx,
            timeout_ms=tool_def.timeout_ms,
            max_retry_count=tool_def.max_retry_count,
            cacheable=tool_def.cacheable,
            max_calls=settings.max_tool_calls_per_request,
        )

        # Populate telemetry IDs if not already set by middleware
        t = result.setdefault("telemetry", {})
        t.setdefault("trace_id", trace_id)
        t.setdefault("request_id", request_id)
        t.setdefault("source_type", result.get("source_type"))
        t.setdefault("external_api_called", False)

        emit_tool_call_trace(
            context=ctx,
            tool_name=tool_def.name,
            status="ok" if result.get("ok") else "degraded" if t.get("degraded") else "error",
            source_type=t.get("source_type"),
            cache_hit=bool(t.get("cache_hit")),
            latency_ms=int(t.get("latency_ms", 0)),
            retry_count=int(t.get("retry_count", 0)),
            degraded=bool(t.get("degraded")),
            degraded_reason=t.get("degraded_reason"),
            environment=settings.app_env,
        )

        return result

    # Copy the handler's signature so FastMCP generates the correct MCP schema
    wrapped.__signature__ = inspect.signature(tool_def.handler)
    wrapped.__name__ = tool_def.name
    wrapped.__doc__ = tool_def.description
    mcp.add_tool(wrapped, name=tool_def.name, description=tool_def.description)
