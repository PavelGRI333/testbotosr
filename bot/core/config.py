from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    token: str


class LLMConfig(BaseSettings):
    provider: str = "gemini"
    api_key: str
    base_url: str = "https://generativelanguage.googleapis.com"
    model: str = "gemini-2.5-flash"
    timeout: float = 60.0
    max_tokens: int = 4096
    temperature: float = 0.0


class IikoServerConfig(BaseSettings):
    """Configuration for optional iiko integration.

    When ``enabled`` is ``False`` all other fields are optional and have
    harmless defaults, allowing the application to start without any iiko
    environment variables.
    """

    enabled: bool = False
    base_url: str = "https://tri-sousa.iiko.it:443"
    login: str = ""
    password_sha1: str = ""
    default_store_id: str = ""
    default_supplier_id: str | None = None
    aliases_path: Path = Path("product_aliases.json")
    timeout: float = 30.0

    # ``host`` is kept for backward compatibility – if provided, ``base_url``
    # will be constructed from it; otherwise the explicit ``base_url`` field is used.
    host: str = ""

    @property
    def effective_base_url(self) -> str:
        if self.host:
            return f"https://{self.host}:443/resto/api"
        return self.base_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    bot: BotSettings
    llm: LLMConfig
    iiko_server: IikoServerConfig | None = None
    temp_dir: Path = Path("./temp")


settings = Settings()
