from dataclasses import dataclass
from typing import Optional

from throughball_ai.config import Settings, get_settings
from throughball_ai.model_router import ModelRouter


@dataclass(frozen=True)
class AdkRuntime:
    service: str
    environment: str
    default_model: str
    max_iterations: int
    vertex_ai_configured: bool


def create_runtime(settings: Optional[Settings] = None) -> AdkRuntime:
    settings = settings or get_settings()
    route = ModelRouter(settings).route("adk_runtime")
    return AdkRuntime(
        service=settings.service_name,
        environment=settings.environment,
        default_model=route.model,
        max_iterations=settings.max_agent_iterations,
        vertex_ai_configured=settings.vertex_ai_configured,
    )
