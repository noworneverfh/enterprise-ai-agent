from __future__ import annotations

import time as perf_time
from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.health import health_check
from app.auth.dependencies import require_permission
from app.core.config import settings
from app.db.session import engine, get_db
from app.models.auth import Role, User
from app.models.diagnosis import AuditLog, DiagnosisRecord, LLMInvocation
from app.services import auth as auth_service
from app.services import audit as audit_service
from app.services.vector_store import ChromaVectorStore


router = APIRouter(
    prefix="/admin/console",
    tags=["Admin Console"],
)

AUDIT_EVENT_TYPES: list[dict[str, str]] = [
    {"value": "user_login", "label": "用户登录"},
    {"value": "login_failed", "label": "登录失败"},
    {"value": "user_register", "label": "用户注册"},
    {"value": "diagnosis_execute", "label": "执行智能诊断"},
    {"value": "risk_analysis", "label": "执行全局风险分析"},
    {"value": "risk_scan", "label": "触发风险扫描"},
    {"value": "knowledge_upload", "label": "上传知识文档"},
    {"value": "knowledge_delete", "label": "删除知识文档"},
    {"value": "maintenance_create", "label": "创建维修记录"},
    {"value": "config_read", "label": "系统配置读取"},
    {"value": "llm_failed", "label": "LLM 调用失败"},
    {"value": "agent_failed", "label": "Agent 执行失败"},
    {"value": "health_failed", "label": "健康检查异常"},
]

AUDIT_ACTION_ALIASES: dict[str, list[str]] = {
    "user_login": ["auth.login:success"],
    "login_failed": ["auth.login:failed"],
    "user_register": ["auth.register"],
    "diagnosis_execute": ["diagnosis.execute"],
    "risk_analysis": ["diagnosis.risk_analysis"],
    "risk_scan": ["risk.scan"],
    "knowledge_upload": ["knowledge.upload"],
    "knowledge_delete": ["knowledge.delete"],
    "maintenance_create": ["maintenance.create"],
    "config_read": ["config.read"],
    "llm_failed": ["llm.failed"],
    "agent_failed": ["agent.failed"],
    "health_failed": ["health.failed"],
}


@router.get("/overview")
def admin_console_overview(
    _current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    health = health_check()
    latest_audit = db.scalar(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(1))
    latest_failure = db.scalar(
        select(AuditLog)
        .where(AuditLog.result != "success")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    today_errors = (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.created_at >= today_start)
            .where(AuditLog.result != "success")
        )
        or 0
    )
    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    active_user_count = (
        db.scalar(select(func.count()).select_from(User).where(User.status == "active"))
        or 0
    )
    llm_metrics = _llm_metrics(db)

    return {
        "checked_at": datetime.utcnow(),
        "environment": settings.app_env,
        "app_version": settings.app_version,
        "core_services": _core_service_summary(health),
        "ai_model": {
            "provider": health["llm"].get("provider"),
            "model": health["llm"].get("model"),
            "mode": health["llm"].get("mode"),
            "reachable": health["llm"].get("reachable"),
        },
        "today_llm_calls": llm_metrics["today_calls"],
        "today_prompt_tokens": llm_metrics["today_prompt_tokens"],
        "today_completion_tokens": llm_metrics["today_completion_tokens"],
        "today_total_tokens": llm_metrics["today_total_tokens"],
        "today_errors": today_errors,
        "registered_users": user_count,
        "active_users": active_user_count,
        "latest_error": _audit_payload(latest_failure) if latest_failure else None,
        "latest_config_change": _audit_payload(latest_audit)
        if latest_audit and "config" in latest_audit.action
        else None,
    }


@router.get("/health")
def admin_console_health(
    _current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    started_at = datetime.utcnow()
    health_latency = _measure(lambda: health_check())
    health = health_latency["result"]
    db_latency = _measure(lambda: db.execute(text("SELECT 1")).scalar())
    vector_latency = _measure(lambda: ChromaVectorStore().collection.count())
    llm_metrics = _llm_metrics(db)
    recent_diagnosis_latency = db.scalar(
        select(DiagnosisRecord.duration_ms)
        .where(DiagnosisRecord.duration_ms.is_not(None))
        .order_by(DiagnosisRecord.created_at.desc())
        .limit(1)
    )

    return {
        "checked_at": started_at,
        "services": [
            {
                "name": "Backend API",
                "status": "healthy" if health["status"] == "ok" else "degraded",
                "latency_ms": health_latency["latency_ms"],
                "description": "FastAPI 应用与业务路由服务",
                "version": settings.app_version,
                "mode": settings.app_env,
                "error": None if health["status"] == "ok" else "One or more dependencies are degraded.",
            },
            {
                "name": _database_label(),
                "status": "healthy" if health["database"] == "connected" else "unhealthy",
                "latency_ms": db_latency["latency_ms"],
                "description": "业务数据持久化服务",
                "version": _database_label(),
                "mode": settings.app_env,
                "error": None if health["database"] == "connected" else "Database connectivity check failed.",
            },
            {
                "name": "ChromaDB",
                "status": "healthy" if health["vector_db"] == "connected" else "unhealthy",
                "latency_ms": vector_latency["latency_ms"],
                "description": "企业维修知识向量检索服务",
                "version": settings.chroma_collection_name,
                "mode": "remote" if settings.chroma_host else "local",
                "error": None if health["vector_db"] == "connected" else "Vector database check failed.",
            },
            {
                "name": "Agent Pipeline",
                "status": "healthy" if all(v == "healthy" for v in _agent_health().values()) else "degraded",
                "latency_ms": recent_diagnosis_latency,
                "description": "Router、Tool、RAG 和报告生成执行链路",
                "version": "Report V2",
                "mode": "runtime" if settings.agent_runtime_enabled else "workflow",
                "error": None,
                "components": _agent_health(),
            },
            {
                "name": "LLM Provider",
                "status": "healthy" if health["llm"].get("reachable") else "unhealthy",
                "latency_ms": llm_metrics["latest_latency_ms"] or health_latency["latency_ms"],
                "description": "AI 模型推理服务健康状态",
                "version": health["llm"].get("model"),
                "mode": health["llm"].get("mode"),
                "error": health["llm"].get("error_type"),
            },
        ],
    }


@router.get("/llm")
def admin_console_llm(
    _current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    health = health_check()
    return {
        "checked_at": datetime.utcnow(),
        "configuration": health["llm"],
        "metrics": _llm_metrics(db),
        "note": "仅统计业务诊断中的真实模型调用；健康检查探测和 Mock 调用不会计入业务模型调用。",
    }


@router.get("/permissions")
def admin_console_permissions(
    _current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    users = db.scalars(select(User).order_by(User.created_at.desc()).limit(100)).all()
    return {
        "roles": [
            {
                "name": "User",
                "description": "查看设备画像、风险事件、诊断报告和维修闭环。",
                "permissions": ["devices:view", "reports:view"],
            },
            {
                "name": "Admin",
                "description": "继承 User 权限，并可执行诊断、管理知识库和系统治理。",
                "permissions": [
                    "devices:view",
                    "reports:view",
                    "diagnosis:execute",
                    "knowledge:upload",
                    "knowledge:delete",
                    "users:manage",
                    "devices:write",
                ],
            },
        ],
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "roles": _product_roles(user),
                "status": user.status,
                "last_login_at": user.last_login_at,
                "created_at": user.created_at,
            }
            for user in users
        ],
        "editable": True,
        "message": "当前权限由 User/Admin 两类产品角色控制；管理员可以在用户治理中调整账号角色或删除无用账号。",
    }


@router.patch("/users/{user_id}/role")
def admin_console_update_user_role(
    user_id: int,
    payload: dict[str, str] = Body(...),
    current_user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    role_name = _normalize_product_role(payload.get("role"))
    if role_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be User or Admin.",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.id == current_user.id and role_name != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove Admin role from the current account.",
        )

    role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        auth_service.ensure_default_roles(db)
        role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Role not initialized.",
        )

    user.roles = [role]
    db.commit()
    db.refresh(user)
    audit_service.record_audit_event(
        db,
        action="user.role_update",
        resource_type="user",
        resource_id=str(user.id),
        result="success",
        user=current_user,
        detail={"target_username": user.username, "role": role_name},
    )
    return _admin_user_payload(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_console_delete_user(
    user_id: int,
    current_user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the current account.",
        )

    username = user.username
    user.roles = []
    db.delete(user)
    db.commit()
    audit_service.record_audit_event(
        db,
        action="user.delete",
        resource_type="user",
        resource_id=str(user_id),
        result="success",
        user=current_user,
        detail={"target_username": username},
    )


@router.get("/audit/event-types")
def admin_console_audit_event_types(
    _current_user=Depends(require_permission("users:manage")),
) -> list[dict[str, str]]:
    return AUDIT_EVENT_TYPES


@router.get("/audit-logs")
def admin_console_audit_logs(
    action_type: str | None = Query(default=None),
    username: str | None = Query(default=None),
    result: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)
    filters = []

    normalized_action = (action_type or "").strip()
    if normalized_action:
        actions = AUDIT_ACTION_ALIASES.get(normalized_action)
        if actions is None:
            filters.append(AuditLog.action == "__unknown_audit_action__")
        else:
            action_filters = []
            for action in actions:
                if ":" in action:
                    action_name, result_name = action.split(":", 1)
                    action_filters.append((AuditLog.action == action_name) & (AuditLog.result == result_name))
                else:
                    action_filters.append(AuditLog.action == action)
            filters.append(action_filters[0] if len(action_filters) == 1 else or_(*action_filters))

    normalized_username = (username or "").strip()
    if normalized_username:
        filters.append(AuditLog.username.ilike(f"%{normalized_username}%"))

    normalized_result = (result or "").strip()
    if normalized_result:
        filters.append(AuditLog.result == normalized_result)

    for filter_ in filters:
        query = query.where(filter_)
        count_query = count_query.where(filter_)

    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_audit_payload(row) for row in rows],
    }


@router.get("/config")
def admin_console_config(
    current_user=Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.audit import record_audit_event

    record_audit_event(
        db,
        action="config.read",
        resource_type="system_config",
        result="success",
        user=current_user,
    )
    base_url = settings.llm_base_url or ""
    return {
        "items": [
            _config_item("运行环境", "APP_ENV", settings.app_env, "影响安全校验策略的运行环境。", "development", True, False),
            _config_item("身份认证", "AUTH_ENABLED", settings.auth_enabled, "是否启用 JWT/RBAC 认证。", False, True, False),
            _config_item("模型服务商", "LLM_PROVIDER", settings.llm_provider, "AI 模型服务供应商。", "mock", True, False),
            _config_item("当前模型", "LLM_MODEL", settings.llm_model or "未配置", "当前使用的模型名称。", "未配置", True, False),
            _config_item("模型服务域名", "LLM_BASE_URL_DOMAIN", _domain(base_url) or "未配置", "AI 服务域名，不展示密钥。", "未配置", True, False),
            _config_item("模型访问密钥", "LLM_API_KEY", "已配置" if settings.llm_api_key else "未配置", "密钥仅显示配置状态。", "未配置", True, True),
            _config_item("Agent Runtime", "AGENT_RUNTIME_ENABLED", settings.agent_runtime_enabled, "是否启用 Agent Runtime。", False, True, False),
            _config_item("知识检索数量", "RAG_TOP_K", "由请求参数控制", "知识检索返回数量，默认由业务请求决定。", "请求控制", False, False),
            _config_item("知识匹配阈值", "KNOWLEDGE_MAX_DISTANCE", settings.knowledge_search_max_distance, "向量检索距离阈值。", 0.55, True, False),
            _config_item("健康缓存时间", "HEALTH_CACHE_TTL", "300 秒", "LLM 健康检查缓存时间。", "300 秒", True, False),
        ],
        "editable": False,
        "message": "当前系统配置通过环境变量和部署配置管理，前端仅提供只读视图。",
    }


def _llm_metrics(db: Session) -> dict[str, Any]:
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    today_invocations = db.scalars(
        select(LLMInvocation)
        .where(LLMInvocation.created_at >= today_start)
        .where(LLMInvocation.purpose == "business")
        .where(LLMInvocation.generation_mode == "real")
    ).all()
    all_invocations = db.scalars(
        select(LLMInvocation)
        .where(LLMInvocation.purpose == "business")
        .where(LLMInvocation.generation_mode == "real")
        .order_by(LLMInvocation.created_at.desc())
        .limit(100)
    ).all()

    success_count = sum(1 for item in today_invocations if item.status == "success")
    failed_count = sum(1 for item in today_invocations if item.status != "success")
    fallback_count = sum(1 for item in today_invocations if item.fallback_occurred == "true")
    today_calls = len(today_invocations)
    durations = [item.latency_ms for item in today_invocations if item.latency_ms is not None]
    latest_success = next((item.created_at for item in all_invocations if item.status == "success"), None)
    latest_failure = next((item.created_at for item in all_invocations if item.status != "success"), None)
    latest_latency = next((item.latency_ms for item in all_invocations if item.latency_ms is not None), None)
    latest_error_type = next((item.error_type for item in all_invocations if item.status != "success"), None)

    return {
        "today_calls": today_calls,
        "today_prompt_tokens": _sum_optional([item.prompt_tokens for item in today_invocations]),
        "today_completion_tokens": _sum_optional([item.completion_tokens for item in today_invocations]),
        "today_total_tokens": _sum_optional([item.total_tokens for item in today_invocations]),
        "avg_latency_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "success_rate": round(success_count / today_calls, 4) if today_calls else None,
        "failure_count": failed_count,
        "fallback_count": fallback_count,
        "success_count": success_count,
        "latest_success_at": latest_success,
        "latest_failure_at": latest_failure,
        "latest_latency_ms": latest_latency,
        "latest_error_type": latest_error_type,
    }


def _audit_payload(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": row.username,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "result": row.result,
        "detail": _safe_detail(row.detail),
        "created_at": row.created_at,
    }


def _safe_detail(detail: Any) -> Any:
    if not isinstance(detail, dict):
        return detail
    return {
        key: value
        for key, value in detail.items()
        if "key" not in key.lower()
        and "token" not in key.lower()
        and "password" not in key.lower()
        and "prompt" not in key.lower()
    }


def _product_roles(user: User) -> list[str]:
    roles = set(auth_service.user_roles(user))
    if "admin" in roles:
        return ["Admin"]
    return ["User"]


def _normalize_product_role(role: str | None) -> str | None:
    normalized = (role or "").strip().lower()
    if normalized in {"admin", "administrator"}:
        return "admin"
    if normalized in {"user", "viewer", "operator"}:
        return "viewer"
    return None


def _admin_user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "roles": _product_roles(user),
        "status": user.status,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def _core_service_summary(health: dict[str, Any]) -> dict[str, Any]:
    states = [
        health.get("status") == "ok",
        health.get("database") == "connected",
        health.get("vector_db") == "connected",
        health.get("llm", {}).get("reachable") is True,
    ]
    return {
        "healthy": sum(1 for state in states if state),
        "total": len(states),
        "status": "healthy" if all(states) else "degraded",
    }


def _agent_health() -> dict[str, str]:
    llm = "healthy"
    if settings.llm_provider == "openai_compatible" and (
        not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model
    ):
        llm = "degraded"
    return {
        "router": "healthy",
        "tools": "healthy",
        "rag": "healthy",
        "llm": llm,
    }


def _database_label() -> str:
    dialect = engine.dialect.name
    if dialect.startswith("postgres"):
        return "PostgreSQL"
    if dialect == "sqlite":
        return "SQLite"
    return dialect


def _domain(url: str) -> str | None:
    return url.replace("https://", "").replace("http://", "").split("/")[0] if url else None


def _config_item(
    label: str,
    name: str,
    value: Any,
    description: str,
    default: Any,
    requires_restart: bool,
    sensitive: bool,
) -> dict[str, Any]:
    return {
        "label": label,
        "name": name,
        "value": value,
        "description": description,
        "default": default,
        "requires_restart": requires_restart,
        "sensitive": sensitive,
        "editable": False,
    }


def _measure(fn):
    started = perf_time.perf_counter()
    result = fn()
    return {
        "result": result,
        "latency_ms": int((perf_time.perf_counter() - started) * 1000),
    }


def _sum_optional(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None

