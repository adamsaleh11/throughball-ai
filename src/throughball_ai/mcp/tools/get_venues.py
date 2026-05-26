from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition

TOOL_NAME = "get_venues"
TIMEOUT_MS = 1200


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

    venues = [
        {
            "venue_id": "venue_pub_1",
            "name": "Example Supporters Pub",
            "venue_type": "pub",
            "neighborhood_id": "nb_king_west",
            "address": "123 Example St",
            "geo": {"lat": 43.6426, "lng": -79.3871},
            "tags": ["supporters", "argentina", "brazil", "watch-party"],
            "source_type": "seeded",
            "last_updated_at": "2026-05-15T00:00:00Z",
        },
        {
            "venue_id": "venue_fanzone_1",
            "name": "Example Matchday Fan Zone",
            "venue_type": "attraction",
            "neighborhood_id": "nb_downtown",
            "address": "456 Example Ave",
            "geo": {"lat": 43.6410, "lng": -79.3890},
            "tags": ["fan-zone", "matchday", "families"],
            "source_type": "seeded",
            "last_updated_at": "2026-05-15T00:00:00Z",
        },
    ]

    if venue_type != "any":
        venues = [venue for venue in venues if venue["venue_type"] == venue_type]
    if neighborhood_id:
        venues = [venue for venue in venues if venue["neighborhood_id"] == neighborhood_id]

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "venues": venues[:limit],
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    cacheable=True,
    max_retry_count=1,
    description="Returns seeded venue records for supporter pubs and fan zones.",
)
