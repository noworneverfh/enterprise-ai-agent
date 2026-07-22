from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.base import LLMMessage
from app.llm.factory import LLMProviderConfigurationError, get_llm_provider
from app.services.vector_store import ChromaVectorStore


router = APIRouter(tags=["Health"])
LLM_HEALTH_CACHE_TTL_SECONDS = 300
_llm_health_cache: tuple[float, dict[str, Any]] | None = None


class _LLMHealthProbe(BaseModel):
    ok: bool


@router.get("/health")
def health_check() -> dict[str, Any]:
    database_status = _check_database()
    vector_status = _check_vector_db()
    llm_status = _check_llm_status()

    overall = (
        "ok"
        if database_status == "connected"
        and vector_status == "connected"
        and llm_status.get("configured") is True
        and llm_status.get("reachable") is True
        else "degraded"
    )
    return {
        "status": overall,
        "database": database_status,
        "vector_db": vector_status,
        "rag": _rag_status_payload(),
        "llm": llm_status,
    }


def _check_database() -> str:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "unavailable"


def _check_vector_db() -> str:
    try:
        store = ChromaVectorStore()
        store.collection.count()
        return "connected"
    except Exception:
        return "unavailable"


def _rag_status_payload() -> dict[str, Any]:
    return {
        "retriever": "chroma",
        "reranker_enabled": settings.reranker_enabled,
        "reranker_model": (
            settings.reranker_model_path
            or settings.reranker_model_name
            if settings.reranker_enabled
            else None
        ),
        "candidate_k": settings.reranker_candidate_k if settings.reranker_enabled else None,
        "mode": "two_stage_rerank" if settings.reranker_enabled else "vector_only",
    }


def _check_llm() -> str:
    return "connected" if _check_llm_status().get("configured") else "unavailable"


def _check_llm_status() -> dict[str, Any]:
    global _llm_health_cache

    cached = _llm_health_cache
    now = time.monotonic()
    if cached is not None and now - cached[0] < LLM_HEALTH_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        provider = get_llm_provider()
    except LLMProviderConfigurationError as exc:
        status = _llm_status_payload(
            configured=False,
            reachable=False,
            error_type=type(exc).__name__,
        )
        _llm_health_cache = (now, status)
        return status
    except Exception as exc:
        status = _llm_status_payload(
            configured=False,
            reachable=False,
            error_type=type(exc).__name__,
        )
        _llm_health_cache = (now, status)
        return status

    provider_name = provider.__class__.__name__
    mode = "mock" if "mock" in provider_name.lower() else "real"
    reachable = True
    error_type = None

    if mode == "real":
        try:
            provider.complete_structured(
                [
                    LLMMessage(
                        role="system",
                        content="Only output a minimal JSON object.",
                    ),
                    LLMMessage(role="user", content='Return {"ok": true}.'),
                ],
                _LLMHealthProbe,
            )
        except Exception as exc:
            reachable = False
            error_type = type(exc).__name__

    status = _llm_status_payload(
        configured=True,
        reachable=reachable,
        provider_class=provider_name,
        mode=mode,
        error_type=error_type,
    )
    _llm_health_cache = (now, status)
    return status


def _llm_status_payload(
    *,
    configured: bool,
    reachable: bool,
    provider_class: str | None = None,
    mode: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    provider = settings.llm_provider.strip().lower()
    base_url = settings.llm_base_url or ""
    return {
        "provider": provider,
        "provider_class": provider_class,
        "model": settings.llm_model,
        "base_url_domain": base_url.replace("https://", "").replace("http://", "").split("/")[0] if base_url else None,
        "configured": configured,
        "reachable": reachable,
        "mode": mode or ("mock" if provider == "mock" else "real"),
        "error_type": error_type,
    }
