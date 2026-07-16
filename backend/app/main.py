from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and clean up application resources."""

    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "AI Agent platform for enterprise knowledge retrieval "
        "and IoT device diagnosis."
    ),
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(health_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": f"{settings.app_name} API",
        "version": settings.app_version,
    }