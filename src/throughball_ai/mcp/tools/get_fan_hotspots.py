from typing import Optional

from throughball_ai.mcp.errors import error_response

TOOL_NAME = "get_fan_hotspots"
TIMEOUT_MS = 1500


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

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "city_id": city_id,
            "match_id": match_id,
            "team_id": team_id,
            "hotspots": [
                {
                    "hotspot_id": "hotspot_1",
                    "venue_id": "venue_pub_1",
                    "name": "Example Supporters Pub",
                    "neighborhood": "King West",
                    "confidence": "medium",
                    "verified_signals": ["Partner venue listing"],
                    "inferred_signals": ["Near stadium transit corridor"],
                    "score": 0.78,
                    "evidence_ids": ["doc_123"],
                }
            ],
            "computed_at": "2026-06-18T16:00:00Z",
        },
    }
