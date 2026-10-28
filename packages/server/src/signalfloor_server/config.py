from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings, read from SIGNALFLOOR_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="SIGNALFLOOR_")

    database_url: str = "postgresql+asyncpg://localhost/signalfloor"
