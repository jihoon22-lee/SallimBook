"""Create this checkout's development settings without overwriting existing files."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    destination = ROOT / ".env"
    if destination.exists() or destination.is_symlink():
        raise SystemExit(
            "Existing .env preserved. Review it locally; no settings were changed."
        )
    database_password = secrets.token_urlsafe(32)
    test_password = secrets.token_urlsafe(32)
    content = (
        "# SallimBook development only; never use these settings for production.\n"
        "SALLIMBOOK_ENVIRONMENT=development\n"
        'SALLIMBOOK_ALLOWED_ORIGINS=["http://localhost:18742","http://127.0.0.1:18742"]\n'
        f"SALLIMBOOK_DATABASE_PASSWORD={database_password}\n"
        f"SALLIMBOOK_TEST_DATABASE_PASSWORD={test_password}\n"
        f"SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook:{database_password}"
        "@127.0.0.1:18744/sallimbook_dev\n"
        f"SALLIMBOOK_TEST_DATABASE_URL=postgresql+psycopg://sallimbook:{test_password}"
        "@127.0.0.1:18745/sallimbook_test\n"
    )
    with os.fdopen(
        os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as file:
        file.write(content)
    print("Created .env with private permissions; no credentials printed.")
