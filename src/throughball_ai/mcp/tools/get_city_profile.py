from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import CityProfileInput, CityProfileOutput
from throughball_ai.repositories.city_data import InMemoryCityProfileRepository, SEEDED_CITY_IDS

TOOL_NAME = "get_city_profile"
TIMEOUT_MS = 1200
_repository = InMemoryCityProfileRepository()


def set_repository(repository) -> None:
    global _repository
    _repository = repository


async def handler(
    city_id: Optional[str] = None,
    include_neighborhoods: bool = True,
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

    profile = _repository.get_city_profile(
        city_id=city_id,
        include_neighborhoods=include_neighborhoods,
    )
    degraded = profile is None
    if profile is None:
        profile = {
            "city_id": city_id,
            "name": None,
            "country_code": None,
            "country": None,
            "timezone": None,
            "summary": None,
            "neighborhoods": [],
            "transit_summary": None,
            "transport_notes": [],
            "matchday_notes": [],
            "safety_notes": [],
            "verified_signals": [],
            "inferred_signals": [],
            "confidence": {
                "level": "none",
                "reason": "No seeded city profile matched the requested city.",
            },
            "last_updated_at": None,
        }
    else:
        profile["confidence"] = {
            "level": profile.get("confidence", "medium"),
            "item_count": 1,
            "reason": "Seeded host city and tourist context.",
        }

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": profile,
        "telemetry": {
            "degraded": degraded,
            "degraded_reason": "PARTIAL_CITY_PROFILE" if degraded else None,
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=CityProfileInput,
    output_schema=CityProfileOutput,
    cacheable=True,
    max_retry_count=1,
    description="Returns seeded city context, neighborhoods, transport notes, and matchday notes.",
)
