from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import FanHotspotsInput, FanHotspotsOutput
from throughball_ai.repositories.city_data import (
    InMemoryHotspotsRepository,
    SEEDED_CITY_IDS,
    aggregate_signals,
    confidence_metadata,
)

TOOL_NAME = "get_fan_hotspots"
TIMEOUT_MS = 1500
_repository = InMemoryHotspotsRepository()


def set_repository(repository) -> None:
    global _repository
    _repository = repository


async def handler(
    city_id: Optional[str] = None,
    match_id: Optional[str] = None,
    team_id: Optional[str] = None,
    limit: int = 10,
    include_evidence: bool = True,
    allow_external: bool = False,
) -> dict:
    if not city_id:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="city_id is required.",
            details={"field": "city_id"},
        )
    if not match_id:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="match_id is required.",
            details={"field": "match_id"},
        )
    if not team_id:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="team_id is required.",
            details={"field": "team_id"},
        )
    if city_id not in SEEDED_CITY_IDS:
        return error_response(
            TOOL_NAME,
            code="CITY_NOT_FOUND",
            message=f"No seeded data for city_id: {city_id}.",
            details={"field": "city_id"},
        )

    hotspots = _repository.list_hotspots(
        city_id=city_id,
        match_id=match_id,
        team_id=team_id,
        limit=limit,
        include_evidence=include_evidence,
    )
    verified_signals, inferred_signals = aggregate_signals(hotspots)
    degraded = len(hotspots) == 0

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "match_id": match_id,
            "team_id": team_id,
            "hotspots": hotspots,
            "verified_signals": verified_signals,
            "inferred_signals": inferred_signals,
            "confidence": confidence_metadata(
                hotspots,
                empty_reason="No seeded hotspots matched the requested city, match, or team.",
            ),
            "computed_at": "2026-06-18T16:00:00Z",
        },
        "telemetry": {
            "degraded": degraded,
            "degraded_reason": "NON_MATCH_SPECIFIC_HOTSPOTS" if degraded else None,
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=FanHotspotsInput,
    output_schema=FanHotspotsOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns backend-computed supporter hotspot candidates and evidence.",
)
