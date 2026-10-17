from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SALLIMBOOK_", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    allowed_origins: list[str] = ["http://localhost:18742", "http://127.0.0.1:18742"]
    database_url: SecretStr | None = None
