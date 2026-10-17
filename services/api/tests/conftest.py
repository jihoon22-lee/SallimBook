import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from sallimbook.core.database import make_engine

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_engine():
    url = os.environ.get("SALLIMBOOK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SALLIMBOOK_TEST_DATABASE_URL not configured; no DB tested")
    parsed = make_url(url)
    if not parsed.database or not parsed.database.endswith("_test"):
        pytest.fail("Database tests require an explicitly named *_test database", pytrace=False)
    schema = "sallimbook_test_" + uuid4().hex
    administration = make_engine(url)
    engine = make_engine(url, schema=schema)
    with administration.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with administration.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        administration.dispose()


@pytest.fixture
def db_session(db_engine):
    with Session(db_engine) as session:
        yield session
