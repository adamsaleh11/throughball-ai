from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import VenuesInput, VenuesOutput
from throughball_ai.repositories.city_data import (
    InMemoryVenuesRepository,
    SEEDED_CITY_IDS,
    aggregate_signals,
    confidence_metadata,
)

TOOL_NAME = "get_venues"
TIMEOUT_MS = 1200
_repository = InMemoryVenuesRepository()


def set_repository(repository) -> None:
    global _repository
    _repository = repository


async def handler(
    city_id: Optional[str] = None,
    venue_type: str = "any",
    neighborhood_id: Optional[str] = None,
    limit: int = 20,
    allow_external: bool = False,
) -> dict:
    if not city_id:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="city_id is required.",
            details={"field": "city_id"},
        )
    if city_id not in SEEDED_CITY_IDS:
        return error_response(
            TOOL_NAME,
            code="CITY_NOT_FOUND",
            message=f"No seeded data for city_id: {city_id}.",
            details={"field": "city_id"},
        )

    venues = _repository.list_venues(
        city_id=city_id,
        venue_type=venue_type,
        neighborhood_id=neighborhood_id,
        limit=limit,
    )
    verified_signals, inferred_signals = aggregate_signals(venues)
    degraded = len(venues) == 0

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "venues": venues,
            "verified_signals": verified_signals,
            "inferred_signals": inferred_signals,
            "confidence": confidence_metadata(
                venues,
                empty_reason="No seeded venues matched the requested filters.",
            ),
        },
        "telemetry": {
            "degraded": degraded,
            "degraded_reason": "FILTERED_VENUES_UNAVAILABLE" if degraded else None,
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=VenuesInput,
    output_schema=VenuesOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns seeded venue records for supporter pubs and fan zones.",
)
