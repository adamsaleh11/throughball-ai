from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import CityEventsInput, CityEventsOutput
from throughball_ai.repositories.city_data import (
    InMemoryEventsRepository,
    SEEDED_CITY_IDS,
    aggregate_signals,
    confidence_metadata,
)

TOOL_NAME = "get_city_events"
TIMEOUT_MS = 1500
_repository = InMemoryEventsRepository()


def set_repository(repository) -> None:
    global _repository
    _repository = repository


async def handler(
    city_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: str = "any",
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

    events = _repository.list_events(
        city_id=city_id,
        start_date=start_date,
        end_date=end_date,
        category=category,
        limit=limit,
    )
    verified_signals, inferred_signals = aggregate_signals(events)
    degraded = len(events) == 0

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "events": events,
            "verified_signals": verified_signals,
            "inferred_signals": inferred_signals,
            "confidence": confidence_metadata(
                events,
                empty_reason="No seeded city events matched the requested filters.",
            ),
        },
        "telemetry": {
            "degraded": degraded,
            "degraded_reason": "DATED_EVENTS_UNAVAILABLE" if degraded else None,
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=CityEventsInput,
    output_schema=CityEventsOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns cached or seeded city events relevant to matchday and fan activity.",
)
