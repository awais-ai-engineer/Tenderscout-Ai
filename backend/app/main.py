from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings
from app.db.session import create_database_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    engine = create_database_engine(settings)
    app.state.settings = settings
    app.state.db_engine = engine
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="TenderScout AI", lifespan=lifespan)
app.include_router(health_router)
