import inspect
from typing import Any

from mcp.server.fastmcp import FastMCP

from throughball_ai.mcp.context import RequestContext
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.settings import MCPSettings
from throughball_ai.mcp.trace import emit_tool_call_trace, new_id
from throughball_ai.mcp.wrappers import execute_with_middleware
from throughball_ai.mcp.tools import (
    get_city_events,
    get_fan_hotspots,
    get_match_state,
    get_venues,
    search_documents,
)

_TOOL_MODULES = [
    get_match_state,
    get_fan_hotspots,
    search_documents,
    get_city_events,
    get_venues,
]


def _build_registry() -> dict[str, ToolDefinition]:
    registry: dict[str, ToolDefinition] = {}
    for module in _TOOL_MODULES:
        defn: ToolDefinition = module.DEFINITION
        defn.validate()
        registry[defn.name] = defn
    return registry


def build_mcp_server(settings: MCPSettings | None = None) -> FastMCP:
    if settings is None:
        settings = MCPSettings()

    registry = _build_registry()
    mcp = FastMCP("throughball-ai")

    for tool_def in registry.values():
        _register_tool(mcp, tool_def, settings)

    return mcp


def _register_tool(mcp: FastMCP, tool_def: ToolDefinition, settings: MCPSettings) -> None:
    async def wrapped(**kwargs: Any) -> dict:
        request_id = new_id("req")
        trace_id = new_id("tr")
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

        t = result.setdefault("telemetry", {})
        t.setdefault("trace_id", trace_id)
        t.setdefault("request_id", request_id)
        t.setdefault("source_type", result.get("source_type"))
        t.setdefault("external_api_called", False)

        status = "ok" if result.get("ok") else "degraded" if t.get("degraded") else "error"
        emit_tool_call_trace(
            context=ctx,
            tool_name=tool_def.name,
            status=status,
            source_type=t.get("source_type"),
            cache_hit=bool(t.get("cache_hit")),
            latency_ms=int(t.get("latency_ms", 0)),
            retry_count=int(t.get("retry_count", 0)),
            degraded=bool(t.get("degraded")),
            degraded_reason=t.get("degraded_reason"),
            environment=settings.app_env,
        )

        return result

    wrapped.__signature__ = inspect.signature(tool_def.handler)
    wrapped.__name__ = tool_def.name
    wrapped.__doc__ = tool_def.description
    mcp.add_tool(wrapped, name=tool_def.name, description=tool_def.description)
