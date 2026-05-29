from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import TeamProfileInput, TeamProfileOutput

TOOL_NAME = "get_team_profile"
TIMEOUT_MS = 1200


async def handler(
    team_id: Optional[str] = None,
    include_evidence: bool = True,
    allow_external: bool = False,
) -> dict:
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
            "team_id": team_id,
            "name": "Example National Team",
            "country": "Example Country",
            "aliases": ["example team", "example country"],
            "supporter_notes": [
                "Supporters commonly gather near partner pubs and fan zones."
            ],
            "rivalries": ["team_rival"],
            "known_supporter_areas": ["King West", "Downtown"],
            "evidence_ids": ["doc_123"] if include_evidence else [],
            "last_updated_at": "2026-05-15T00:00:00Z",
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=TeamProfileInput,
    output_schema=TeamProfileOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns seeded team context, aliases, supporter notes, and evidence references.",
)
