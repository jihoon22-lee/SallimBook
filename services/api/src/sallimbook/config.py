from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALLIMBOOK_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    # Read the already validated environment only when no origin list was explicitly supplied.
    allowed_origins: list[str] = Field(
        default_factory=lambda data: (
            ["http://localhost:18742", "http://127.0.0.1:18742"]
            if data["environment"] in ("development", "test")
            else []
        )
    )
    database_url: SecretStr | None = None
