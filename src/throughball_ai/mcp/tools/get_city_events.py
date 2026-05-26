from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition

TOOL_NAME = "get_city_events"
TIMEOUT_MS = 1500


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

    events = [
        {
            "event_id": "event_matchday_1",
            "name": "Example Matchday Fan Zone",
            "category": "matchday",
            "starts_at": "2026-06-18T18:00:00-04:00",
            "ends_at": "2026-06-18T23:30:00-04:00",
            "venue_id": "venue_fanzone_1",
            "source_type": "seeded",
            "confidence": "medium",
        },
        {
            "event_id": "event_pub_1",
            "name": "Example Supporters Pub Watch Party",
            "category": "matchday",
            "starts_at": "2026-06-18T19:00:00-04:00",
            "ends_at": "2026-06-18T22:00:00-04:00",
            "venue_id": "venue_pub_1",
            "source_type": "seeded",
            "confidence": "medium",
        },
    ]

    if category != "any":
        events = [event for event in events if event["category"] == category]

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "events": events[:limit],
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    cacheable=True,
    max_retry_count=1,
    description="Returns cached or seeded city events relevant to matchday and fan activity.",
)
