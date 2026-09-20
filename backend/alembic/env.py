from alembic import context
from app.core.config import Settings
from app.db.session import create_database_engine
from app.models import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    engine = create_database_engine(Settings())
    try:
        if context.is_offline_mode():
            context.configure(
                url=engine.url,
                target_metadata=target_metadata,
                literal_binds=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        else:
            with engine.connect() as connection:
                context.configure(
                    connection=connection, target_metadata=target_metadata
                )
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
