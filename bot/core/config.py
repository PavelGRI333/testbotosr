from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    token: str


class GeminiSettings(BaseSettings):
    api_key: str
    model: str = "gemini-2.5-flash"


class IikoServerSettings(BaseSettings):
    host: str
    login: str
    password_sha1: str = Field(..., description="SHA1 of password")
    default_store_id: str
    default_supplier_id: str | None = None
    aliases_path: Path = Path("product_aliases.json")

    @property
    def base_url(self) -> str:
        """Base URL for iiko RMS API (derived from host)."""
        return f"https://{self.host}:443/resto/api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    bot: BotSettings
    gemini: GeminiSettings
    iiko_server: IikoServerSettings
    temp_dir: Path = Path("./temp")


settings = Settings()
