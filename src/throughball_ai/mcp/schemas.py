from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["seeded", "cached", "internal", "external", "none"]


class ToolTelemetry(BaseModel):
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    latency_ms: int = 0
    cache_hit: bool = False
    source_type: Optional[SourceType] = None
    retry_count: int = 0
    degraded: bool = False
    degraded_reason: Optional[str] = None
    external_api_called: bool = False


class ToolErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False
    degraded_available: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class BaseToolInput(BaseModel):
    allow_external: bool = False


class BaseToolResponse(BaseModel):
    ok: bool
    tool: str
    source_type: Optional[SourceType] = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[ToolErrorPayload] = None
    telemetry: ToolTelemetry = Field(default_factory=ToolTelemetry)


class MatchStateInput(BaseToolInput):
    match_id: str
    include_timeline: bool = False


class FanHotspotsInput(BaseToolInput):
    city_id: str
    match_id: str
    team_id: str
    limit: int = Field(default=10, ge=1, le=50)
    include_evidence: bool = True


class CityEventsInput(BaseToolInput):
    city_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: str = "any"
    limit: int = Field(default=20, ge=1, le=50)


class VenuesInput(BaseToolInput):
    city_id: str
    venue_type: str = "any"
    neighborhood_id: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=50)


class SearchDocumentsInput(BaseToolInput):
    query: str
    city_id: Optional[str] = None
    team_id: Optional[str] = None
    category: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=8)
    filters: Optional[dict[str, Any]] = None
    limit: Optional[int] = Field(default=None, ge=1, le=8)
    include_snippets: bool = True


class TeamProfileInput(BaseToolInput):
    team_id: str
    include_evidence: bool = True


class CityProfileInput(BaseToolInput):
    city_id: str
    include_neighborhoods: bool = True


MatchStateOutput = BaseToolResponse
FanHotspotsOutput = BaseToolResponse
CityEventsOutput = BaseToolResponse
VenuesOutput = BaseToolResponse
SearchDocumentsOutput = BaseToolResponse
TeamProfileOutput = BaseToolResponse
CityProfileOutput = BaseToolResponse
