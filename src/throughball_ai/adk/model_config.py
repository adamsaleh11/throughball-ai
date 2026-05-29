from dataclasses import dataclass
from typing import Optional

from throughball_ai.config import Settings, get_settings
from throughball_ai.model_router import ModelRouter


@dataclass(frozen=True)
class AdkModelConfig:
    agent_name: str
    model_name: str
    max_output_tokens: int
    temperature: float
    max_iterations: int
    gemini_pro_enabled: bool = False


def create_model_config(
    *,
    agent_name: str,
    settings: Optional[Settings] = None,
    max_iterations: Optional[int] = None,
) -> AdkModelConfig:
    settings = settings or get_settings()
    route = ModelRouter(settings).route(agent_name)
    return AdkModelConfig(
        agent_name=agent_name,
        model_name=route.model,
        max_output_tokens=route.max_output_tokens,
        temperature=route.temperature,
        max_iterations=max_iterations or settings.max_agent_iterations,
    )
