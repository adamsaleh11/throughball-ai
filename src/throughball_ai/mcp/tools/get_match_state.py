from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition

TOOL_NAME = "get_match_state"
TIMEOUT_MS = 1200


async def handler(
    match_id: Optional[str] = None,
    include_timeline: bool = False,
    allow_external: bool = False,
) -> dict:
    if not match_id:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="match_id is required.",
            details={"field": "match_id"},
        )

    data = {
        "match_id": match_id,
        "home_team_id": "team_home",
        "away_team_id": "team_away",
        "status": "live",
        "minute": 67,
        "score": {"home": 2, "away": 1},
        "venue_id": "venue_456",
        "competition": "World Cup",
        "started_at": "2026-06-18T19:00:00Z",
        "last_updated_at": "2026-06-18T20:24:00Z",
    }

    if include_timeline:
        data["timeline"] = [
            {
                "minute": 64,
                "event_type": "goal",
                "team_id": "team_home",
                "player_id": "player_9",
                "description": "Goal from open play.",
            }
        ]

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": data,
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    cacheable=True,
    max_retry_count=1,
    description="Returns current or cached match status, score, clock, and basic momentum inputs.",
)
