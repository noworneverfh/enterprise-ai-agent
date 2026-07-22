from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging
import time

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.context import router as context_router
from app.api.dashboard import router as dashboard_router
from app.api.devices import router as devices_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import engine
from app.llm.factory import LLMProviderConfigurationError, close_llm_provider
from app.conversation.models import Conversation, Message  # noqa: F401
from app.models import (  # noqa: F401
    AuditLog,
    DeviceContextSnapshot,
    Device,
    DeviceAlarmRecord,
    DeviceRiskTimeline,
    DiagnosisFeedback,
    DeviceRuntimeData,
    DiagnosisReport,
    DiagnosisRecord,
    DiagnosisSession,
    DiagnosisTrace,
    KnowledgeChunk,
    KnowledgeDocument,
    MaintenanceRecord,
    Permission,
    RiskEvent,
    Role,
    User,
)
from app.db.session import SessionLocal
from app.services.auth import ensure_default_roles

configure_logging()
request_logger = logging.getLogger("request")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and clean up application resources."""

    settings.validate_runtime_security()
    if settings.allow_create_all:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_roles(db)
    finally:
        db.close()
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
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(devices_router)
app.include_router(knowledge_router)
app.include_router(agent_router)
app.include_router(dashboard_router)
app.include_router(context_router)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    request_logger.info(
        "request method=%s path=%s status_code=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


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
