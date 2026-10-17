from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Column, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from sallimbook.config import Settings
from sallimbook.core.types import KrwNumeric
from sallimbook.identity.models import Household
from sallimbook.main import create_app

pytestmark = pytest.mark.database


def test_migration_round_trip_and_timezone(db_engine):
    with db_engine.connect() as connection:
        assert connection.scalar(text("SHOW timezone")) == "UTC"
        connection.commit()
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        assert inspect(connection).has_table("households")
        connection.commit()
        command.downgrade(config, "base")
        assert not inspect(connection).has_table("households")
        connection.commit()
        command.upgrade(config, "head")
        assert inspect(connection).has_table("households")


def test_household_currency_is_enforced_in_postgres(db_engine):
    with Session(db_engine) as session:
        session.add(Household(name="합성 가계", base_currency="USD"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_optimistic_versioning_rejects_lost_update(db_engine):
    with Session(db_engine) as seed:
        household = Household(name="합성 가계")
        seed.add(household)
        seed.commit()
        identity = household.id
    with Session(db_engine) as first, Session(db_engine) as second:
        a = first.get(Household, identity)
        b = second.get(Household, identity)
        assert a.version == b.version == 1
        a.name = "합성 가계 A 수정"
        first.commit()
        b.name = "합성 가계 B 수정"
        with pytest.raises(StaleDataError):
            second.commit()
    with Session(db_engine) as verify:
        assert verify.get(Household, identity).name == "합성 가계 A 수정"


def test_postgres_preserves_twenty_digit_amount_and_null(db_engine):
    table = Table(
        "amount_probe",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("amount", KrwNumeric, nullable=True),
    )
    table.create(db_engine)
    with db_engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {"id": 1, "amount": Decimal("99999999999999999999")},
                {"id": 2, "amount": Decimal("0")},
                {"id": 3, "amount": None},
            ],
        )
        assert connection.execute(select(table.c.amount).order_by(table.c.id)).scalars().all() == [
            Decimal("99999999999999999999"),
            Decimal("0"),
            None,
        ]
    for invalid in (1.25, Decimal("1.25")):
        with pytest.raises(StatementError), db_engine.begin() as connection:
            connection.execute(table.insert(), {"id": 4, "amount": invalid})


def test_readiness_requires_current_migration(db_engine, monkeypatch):
    monkeypatch.setattr("sallimbook.main.make_engine", lambda _: db_engine)
    app = create_app(Settings(environment="test", database_url=SecretStr("configured")))
    with TestClient(app) as client:
        assert client.get("/api/v1/ready").status_code == 200
        with db_engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='old_revision'"))
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SCHEMA_UNAVAILABLE"
