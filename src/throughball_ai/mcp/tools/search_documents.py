from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition

TOOL_NAME = "search_documents"
TIMEOUT_MS = 1800


async def handler(
    query: Optional[str] = None,
    filters: Optional[dict] = None,
    limit: int = 5,
    include_snippets: bool = True,
    allow_external: bool = False,
) -> dict:
    if not query:
        return error_response(
            TOOL_NAME,
            code="INVALID_INPUT",
            message="query is required.",
            details={"field": "query"},
        )

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "results": [
                {
                    "document_id": "doc_123",
                    "document_type": "venue_evidence",
                    "title": "Supporter Pub Listing",
                    "snippet": "Partner listing identifies this venue as a supporters gathering location.",
                    "source_type": "cached",
                    "relevance_score": 0.84,
                    "created_at": "2026-05-15T00:00:00Z",
                }
            ]
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    cacheable=True,
    max_retry_count=1,
    description="Searches retrieved evidence documents for agent synthesis.",
)
