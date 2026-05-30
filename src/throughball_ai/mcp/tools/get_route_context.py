from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import RouteContextInput, RouteContextOutput
from throughball_ai.repositories.city_data import (
    InMemoryRouteContextRepository,
    SEEDED_CITY_IDS,
)

TOOL_NAME = "get_route_context"
TIMEOUT_MS = 1500
_repository = InMemoryRouteContextRepository()


def set_repository(repository) -> None:
    global _repository
    _repository = repository


async def handler(
    city_id: Optional[str] = None,
    origin: Optional[dict] = None,
    destination: Optional[dict] = None,
    departure_time: Optional[str] = None,
    mode: str = "any",
    allow_external: bool = False,
) -> dict:
    if not city_id:
        return error_response(
            TOOL_NAME, code="INVALID_INPUT", message="city_id is required.",
            details={"field": "city_id"},
        )
    if not origin or not origin.get("id"):
        return error_response(
            TOOL_NAME, code="INVALID_INPUT", message="origin.id is required.",
            details={"field": "origin"},
        )
    if not destination or not destination.get("id"):
        return error_response(
            TOOL_NAME, code="INVALID_INPUT", message="destination.id is required.",
            details={"field": "destination"},
        )
    if city_id not in SEEDED_CITY_IDS:
        return error_response(
            TOOL_NAME, code="DATA_UNAVAILABLE",
            message=f"No seeded route data for city_id: {city_id}.",
            details={"field": "city_id"},
        )

    origin_id = origin["id"]
    destination_id = destination["id"]

    route = _repository.get_route(
        city_id=city_id,
        origin_id=origin_id,
        destination_id=destination_id,
        mode=mode,
    )
    if route is not None:
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "source_type": "seeded",
            "data": {
                "city_id": city_id,
                "origin_id": origin_id,
                "destination_id": destination_id,
                **route,
            },
            "telemetry": {
                "degraded": False,
                "degraded_reason": None,
                "source_type": "seeded",
                "external_api_called": False,
            },
        }

    # Point-to-point miss: degrade to static city transit guidance, no precise duration.
    fallback = _repository.static_city_context(city_id=city_id, mode=mode)
    if fallback is None:
        return error_response(
            TOOL_NAME, code="ROUTE_NOT_FOUND",
            message="No route or static context available for the requested points.",
        )
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "origin_id": origin_id,
            "destination_id": destination_id,
            **fallback,
        },
        "telemetry": {
            "degraded": True,
            "degraded_reason": "POINT_TO_POINT_ROUTE_UNAVAILABLE",
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=RouteContextInput,
    output_schema=RouteContextOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns seeded approximate route and transit context between two known points.",
)
