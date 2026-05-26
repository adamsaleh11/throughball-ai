from dataclasses import dataclass

from throughball_ai.config import Settings


@dataclass(frozen=True)
class ModelRoute:
    agent_name: str
    model: str
    max_output_tokens: int
    temperature: float
    escalated: bool


class ModelRouter:
    def __init__(self, settings: Settings):
        self._settings = settings

    def route(self, agent_name: str, escalate: bool = False) -> ModelRoute:
        return ModelRoute(
            agent_name=agent_name,
            model=self._settings.gemini_flash_model,
            max_output_tokens=self._settings.max_output_tokens,
            temperature=self._settings.default_temperature,
            escalated=escalate,
        )
