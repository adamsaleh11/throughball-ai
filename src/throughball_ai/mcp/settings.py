from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    ai_api_host: str = Field(default="127.0.0.1", alias="AI_API_HOST")
    ai_api_port: int = Field(default=8001, alias="AI_API_PORT")
    max_tool_calls_per_request: int = Field(default=5, alias="MAX_TOOL_CALLS_PER_REQUEST", ge=1)
    # Accepts ENVIRONMENT (shared with Settings) or APP_ENV for backward compat
    app_env: str = Field(
        default="local",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
