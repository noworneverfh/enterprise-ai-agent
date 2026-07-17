from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.api.agent import router as agent_router
from app.api.devices import router as devices_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.llm.factory import LLMProviderConfigurationError, close_llm_provider
from app.conversation.models import Conversation, Message  # noqa: F401
from app.models import (  # noqa: F401
    Device,
    DeviceAlarmRecord,
    DeviceRuntimeData,
    KnowledgeChunk,
    KnowledgeDocument,
)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and clean up application resources."""

    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        close_llm_provider()


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
app.include_router(devices_router)
app.include_router(knowledge_router)
app.include_router(agent_router)


@app.exception_handler(LLMProviderConfigurationError)
async def llm_provider_configuration_exception_handler(
    request: Request,
    exc: LLMProviderConfigurationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "LLM provider is not available."},
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": f"{settings.app_name} API",
        "version": settings.app_version,
    }
