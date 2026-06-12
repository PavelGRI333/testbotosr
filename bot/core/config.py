from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    token: str


class GeminiSettings(BaseSettings):
    api_key: str
    model: str = "gemini-2.5-flash"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    bot: BotSettings
    gemini: GeminiSettings
    temp_dir: Path = Path("./temp")


settings = Settings()
