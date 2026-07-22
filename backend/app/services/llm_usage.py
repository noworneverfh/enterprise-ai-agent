from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.diagnosis import LLMInvocation


def persist_llm_invocation(
    db: Session,
    *,
    metadata: dict[str, Any] | None,
    report_id: str | None,
    user_id: int | None,
    purpose: str = "business",
) -> None:
    """Persist one real LLM usage metadata record when token usage is available."""

    if not isinstance(metadata, dict):
        return
    if metadata.get("generation_mode") != "real":
        return
    if str(metadata.get("provider") or "").lower() == "mock":
        return
    status = str(metadata.get("status") or "success")
    if status == "success" and metadata.get("total_tokens") is None and metadata.get("prompt_tokens") is None:
        return

    created_at = metadata.get("created_at")
    parsed_created_at = None
    if isinstance(created_at, str):
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            parsed_created_at = None

    db.add(
        LLMInvocation(
            request_id=_string_or_none(metadata.get("request_id")),
            response_id=_string_or_none(metadata.get("response_id")),
            report_id=report_id,
            user_id=user_id,
            provider=str(metadata.get("provider") or "unknown"),
            model=_string_or_none(metadata.get("model")),
            base_url_domain=_string_or_none(metadata.get("base_url_domain")),
            mode=_string_or_none(metadata.get("mode")),
            generation_mode=str(metadata.get("generation_mode") or "real"),
            prompt_tokens=_int_or_none(metadata.get("prompt_tokens")),
            completion_tokens=_int_or_none(metadata.get("completion_tokens")),
            total_tokens=_int_or_none(metadata.get("total_tokens")),
            latency_ms=_int_or_none(metadata.get("latency_ms")),
            fallback_occurred=str(bool(metadata.get("fallback_occurred"))).lower(),
            status=status,
            error_type=_string_or_none(metadata.get("error_type")),
            purpose=purpose,
            created_at=parsed_created_at or datetime.utcnow(),
        )
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
