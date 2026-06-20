from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    token: str


class LLMSettings(BaseModel):
    api_key: str
    model: str = "google/gemini-3.1-pro-preview"
    base_url: str = "https://openrouter.ai/api/v1"
    temperature: float = 0.0
    http_referer: str | None = None
    app_title: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    bot: BotSettings
    llm: LLMSettings
    temp_dir: Path = Path("./temp")


settings = Settings()  # type: ignore[call-arg]
