from pathlib import Path
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
    # Passkeys require the actual HTTPS RP and signed Android origins to be configured.
    webauthn_rp_id: str | None = None
    webauthn_web_origins: list[str] = Field(default_factory=list)
    webauthn_native_origins: list[str] = Field(default_factory=list)
    field_encryption_key_file: Path | None = None
    document_storage_directory: Path | None = None
    document_scanner_socket: Path | None = None
    document_tesseract_path: Path = Path("/usr/bin/tesseract")
    document_pdftoppm_path: Path = Path("/usr/bin/pdftoppm")
    document_household_quota_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    document_household_quota_count: int = Field(default=200, ge=1)
    document_global_quota_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1)
    document_global_quota_count: int = Field(default=2000, ge=1)
    document_min_free_bytes: int = Field(default=1024 * 1024 * 1024, ge=0)
