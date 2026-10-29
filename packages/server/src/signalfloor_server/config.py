from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings, read from SIGNALFLOOR_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="SIGNALFLOOR_")

    database_url: str = "postgresql+asyncpg://localhost/signalfloor"
    # Comma separated. With none, the API is open, which is only safe on your own machine.
    # More than one lets you rotate: add the new key, move clients over, remove the old one.
    api_keys: str = ""

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(k.strip() for k in self.api_keys.split(",") if k.strip())
