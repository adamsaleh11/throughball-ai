from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="local", alias="ENVIRONMENT")
    service_name: str = Field(default="throughball-ai", alias="SERVICE_NAME")
    google_cloud_project: Optional[str] = Field(default=None, alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: Optional[str] = Field(default=None, alias="GOOGLE_CLOUD_LOCATION")
    vertex_ai_enabled: bool = Field(default=True, alias="VERTEX_AI_ENABLED")
    gemini_flash_model: str = Field(
        default="gemini-2.0-flash-001",
        alias="GEMINI_FLASH_MODEL",
    )
    max_output_tokens: int = Field(default=512, alias="MAX_OUTPUT_TOKENS", ge=1)
    default_temperature: float = Field(default=0.2, alias="DEFAULT_TEMPERATURE", ge=0, le=2)
    max_agent_iterations: int = Field(default=3, alias="MAX_AGENT_ITERATIONS", ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def vertex_ai_configured(self) -> bool:
        return bool(
            self.vertex_ai_enabled
            and self.google_cloud_project
            and self.google_cloud_location
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
