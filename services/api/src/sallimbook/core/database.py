import re
from collections.abc import Generator
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import BigInteger, DateTime, MetaData, create_engine, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column

from sallimbook.core.errors import DomainError

CONVENTIONS = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
REQUIRED_SCHEMA_REVISION = "0025_card_stored_details"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENTIONS)


class EntityMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


def make_engine(url: str, *, schema: str | None = None) -> Engine:
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("Use the PostgreSQL psycopg driver")
    options = "-c timezone=UTC"
    if schema is not None:
        if not re.fullmatch(r"sallimbook_test_[a-f0-9]{32}", schema):
            raise ValueError("Invalid isolated test schema")
        options += f" -c search_path={schema}"
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": options},
    )


def get_session(request: Request) -> Generator[Session]:
    engine = request.app.state.engine
    if engine is None:
        raise DomainError("DATABASE_UNAVAILABLE", "데이터 저장소 연결을 확인해 주세요.", 503)
    # Services commit their explicit transaction before returning. Closing rolls back leftovers.
    with Session(engine) as session:
        yield session
