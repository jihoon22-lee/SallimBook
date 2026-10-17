from alembic import context

from sallimbook import models  # noqa: F401
from sallimbook.config import Settings
from sallimbook.core.database import Base, make_engine

provided_connection = context.config.attributes.get("connection")
settings = Settings()
if settings.database_url is None and provided_connection is None:
    raise RuntimeError("SALLIMBOOK_DATABASE_URL is required for migrations")

if context.is_offline_mode():
    assert settings.database_url is not None
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif provided_connection is not None:
    context.configure(
        connection=provided_connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    assert settings.database_url is not None
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
