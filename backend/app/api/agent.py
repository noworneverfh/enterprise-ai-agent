import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.agent.risk_analysis import run_multi_device_risk_analysis
from app.agent.runtime import run_agent_runtime_diagnosis
from app.agent.trace import get_latest_agent_trace
from app.agent.workflow import run_agent_diagnosis
from app.core.config import settings
from app.auth.dependencies import require_permission
from app.context.schemas import DiagnosisSessionCreate
from app.context.session_context import persist_diagnosis_session
from app.db.session import get_db
from app.domain.diagnosis.compatibility import (
    attach_fleet_report_v2,
    attach_single_report_v2,
)
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.models.auth import User
from app.models.diagnosis import DiagnosisRecord
from app.schemas.agent import (
    AgentDiagnoseRequest,
    AgentDiagnoseResponse,
    MultiDeviceRiskRequest,
    MultiDeviceRiskResponse,
)
from app.services.audit import record_audit_event
from app.services.llm_usage import persist_llm_invocation
from app.services.reporting import persist_report_v2


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
)


@router.post(
    "/diagnose",
    response_model=AgentDiagnoseResponse,
)
def diagnose(
    request: AgentDiagnoseRequest,
    report_version: str = Header(default="1.0", alias="X-Report-Version"),
    current_user: User | None = Depends(require_permission("diagnosis:execute")),
    db: Session = Depends(get_db),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> AgentDiagnoseResponse:
    started_at = time.perf_counter()
    try:
        if settings.agent_runtime_enabled:
            response = run_agent_runtime_diagnosis(
                db=db,
                request=request,
                llm_provider=llm_provider,
            )
        else:
            response = run_agent_diagnosis(
                db=db,
                request=request,
                llm_provider=llm_provider,
            )

        enriched_response = attach_single_report_v2(
            response,
            _get_matching_latest_trace(request),
        )
        try:
            _save_diagnosis_record(
                db=db,
                request=request,
                response=enriched_response,
                duration_ms=max(1, round((time.perf_counter() - started_at) * 1000)),
                current_user=current_user,
                provider_type=_provider_type(llm_provider),
                llm_metadata=getattr(llm_provider, "last_call_metadata", None),
            )
            record_audit_event(
                db,
                action="diagnosis.execute",
                resource_type="diagnosis_record",
                result="success",
                user=current_user,
                detail={"query": request.query, "device_code": request.device_code},
            )
        except Exception:
            if hasattr(db, "rollback"):
                db.rollback()
            logger.exception("Failed to save diagnosis history record.")
        return enriched_response if report_version == "2.0" else response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected agent diagnosis API failure.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent diagnosis failed due to an internal error.",
        ) from exc


@router.get("/debug/trace/latest")
def latest_agent_trace(
    _current_user: User | None = Depends(require_permission("reports:view")),
) -> dict[str, Any]:
    trace = get_latest_agent_trace()
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent trace not found.",
        )

    return trace


@router.post(
    "/risk-analysis",
    response_model=MultiDeviceRiskResponse,
)
def analyze_all_device_risk(
    request: MultiDeviceRiskRequest,
    report_version: str = Header(default="1.0", alias="X-Report-Version"),
    current_user: User | None = Depends(require_permission("diagnosis:execute")),
    db: Session = Depends(get_db),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> MultiDeviceRiskResponse:
    started_at = time.perf_counter()
    try:
        response = run_multi_device_risk_analysis(
            db=db,
            request=request,
            llm_provider=llm_provider,
        )
        enriched_response = attach_fleet_report_v2(
            response,
            get_latest_agent_trace(),
        )
        try:
            _save_risk_analysis_record(
                db=db,
                request=request,
                response=enriched_response,
                duration_ms=max(1, round((time.perf_counter() - started_at) * 1000)),
                current_user=current_user,
                provider_type=_provider_type(llm_provider),
                llm_metadata=getattr(llm_provider, "last_call_metadata", None),
            )
            record_audit_event(
                db,
                action="diagnosis.risk_analysis",
                resource_type="diagnosis_record",
                result="success",
                user=current_user,
                detail={"query": request.query},
            )
        except Exception:
            if hasattr(db, "rollback"):
                db.rollback()
            logger.exception("Failed to save risk analysis history record.")
        return enriched_response if report_version == "2.0" else response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected multi-device risk analysis API failure.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Multi-device risk analysis failed due to an internal error.",
        ) from exc


def _save_diagnosis_record(
    db: Session,
    request: AgentDiagnoseRequest,
    response: AgentDiagnoseResponse,
    duration_ms: int,
    current_user: User | None,
    provider_type: str,
    llm_metadata: dict[str, Any] | None = None,
) -> None:
    if not all(hasattr(db, method_name) for method_name in ("add", "commit")):
        logger.warning("Skipping diagnosis history save because db session is unavailable.")
        return

    trace = _get_matching_latest_trace(request)
    confidence = _calculate_diagnosis_confidence(response=response, trace=trace)
    record = DiagnosisRecord(
        device_code=response.device.device_code if response.device else request.device_code,
        alarm_code=_extract_alarm_code(response=response, query=request.query),
        risk_level=response.risk_level,
        status="completed",
        query=request.query,
        problem_summary=response.problem_summary,
        response_json={
            "response": response.model_dump(mode="json"),
            "trace": trace,
            "tools_used": list(response.tools_used),
            "rag_sources": _extract_rag_sources(response=response, trace=trace),
            "confidence": confidence,
        },
        duration_ms=duration_ms,
    )
    db.add(record)
    db.flush()
    session = _persist_business_session(
        db=db,
        record=record,
        query=request.query,
        trace=trace,
        report=getattr(response, "report_v2", None),
        user_id=current_user.id if current_user else None,
        device_id=response.device.id if response.device else None,
    )
    report_v2 = getattr(response, "report_v2", None)
    if report_v2 is not None and hasattr(report_v2, "model_copy"):
        report_v2 = report_v2.model_copy(update={"diagnosis_session_id": session.session_id})
        response.report_v2 = report_v2
        if isinstance(trace, dict):
            trace["diagnosis_session_id"] = session.session_id
    persist_report_v2(
        db,
        record=record,
        report=report_v2,
        trace=trace,
        provider_type=provider_type,
        generation_status=_generation_status_from_warnings(response.warnings),
        user_id=current_user.id if current_user else None,
    )
    persist_llm_invocation(
        db,
        metadata=llm_metadata,
        report_id=record.report_id,
        user_id=current_user.id if current_user else None,
    )
    db.commit()


def _save_risk_analysis_record(
    db: Session,
    request: MultiDeviceRiskRequest,
    response: MultiDeviceRiskResponse,
    duration_ms: int,
    current_user: User | None,
    provider_type: str,
    llm_metadata: dict[str, Any] | None = None,
) -> None:
    if not all(hasattr(db, method_name) for method_name in ("add", "commit")):
        logger.warning("Skipping risk analysis history save because db session is unavailable.")
        return

    trace = get_latest_agent_trace()
    record = DiagnosisRecord(
        device_code=None,
        alarm_code=_extract_primary_risk_alarm(response),
        risk_level=response.overall_risk_level,
        status="completed",
        query=request.query,
        problem_summary=response.summary,
        response_json={
            "risk_report": response.model_dump(mode="json"),
            "trace": trace,
            "tools_used": list(response.tools_used),
            "rag_sources": _extract_rag_sources_from_sources(response.sources, trace),
            "confidence": response.confidence,
        },
        duration_ms=duration_ms,
    )
    db.add(record)
    db.flush()
    session = _persist_business_session(
        db=db,
        record=record,
        query=request.query,
        trace=trace,
        report=getattr(response, "report_v2", None),
        user_id=current_user.id if current_user else None,
        device_id=None,
    )
    report_v2 = getattr(response, "report_v2", None)
    if report_v2 is not None and hasattr(report_v2, "model_copy"):
        report_v2 = report_v2.model_copy(update={"diagnosis_session_id": session.session_id})
        response.report_v2 = report_v2
        if isinstance(trace, dict):
            trace["diagnosis_session_id"] = session.session_id
    persist_report_v2(
        db,
        record=record,
        report=report_v2,
        trace=trace,
        provider_type=provider_type,
        generation_status=_generation_status_from_warnings(response.warnings),
        user_id=current_user.id if current_user else None,
    )
    persist_llm_invocation(
        db,
        metadata=llm_metadata,
        report_id=record.report_id,
        user_id=current_user.id if current_user else None,
    )
    db.commit()


def _generation_status_from_warnings(warnings: list[str]) -> str:
    warning_text = " ".join(warnings).lower()
    if "fallback" in warning_text or "unavailable" in warning_text:
        return "fallback"
    return "completed"


def _persist_business_session(
    *,
    db: Session,
    record: DiagnosisRecord,
    query: str,
    trace: dict[str, Any] | None,
    report: Any,
    user_id: int | None,
    device_id: int | None,
) -> Any:
    trace_payload = trace if isinstance(trace, dict) else {}
    report_payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else {}
    session = persist_diagnosis_session(
        db,
        DiagnosisSessionCreate(
            request_id=str(trace_payload.get("trace_id") or record.report_id),
            user_id=user_id,
            device_id=device_id,
            report_id=record.report_id,
            query=query,
            intent=str(trace_payload.get("mode") or "diagnosis"),
            planned_tools=[
                str(item)
                for item in trace_payload.get("router_tools", [])
                if isinstance(item, str)
            ],
            evidence_summary={
                "device_context": trace_payload.get("device_context"),
                "tool_results": trace_payload.get("tool_results", []),
            },
            rag_summary=[
                item
                for item in trace_payload.get("rag_results", [])
                if isinstance(item, dict)
            ],
            risk_summary=report_payload.get("risk")
            or report_payload.get("overall_risk")
            or {},
            report_summary={
                "report_version": report_payload.get("report_version"),
                "generation_mode": report_payload.get("generation_mode"),
                "conclusion": report_payload.get("conclusion") or report_payload.get("summary"),
                "data_gaps": report_payload.get("data_gaps", []),
            },
            status=record.status,
        ),
    )
    db.flush()
    return session


def _provider_type(llm_provider: LLMProvider) -> str:
    provider_name = llm_provider.__class__.__name__.lower()
    if "mock" in provider_name:
        return "mock"
    if "ollama" in provider_name:
        return "ollama"
    if "openai" in provider_name:
        return "openai_compatible"
    return settings.llm_provider


def _extract_alarm_code(
    response: AgentDiagnoseResponse,
    query: str,
) -> str | None:
    if response.recent_alarms:
        return response.recent_alarms[0].alarm_code

    matched = re.search(r"\bE\d{3,}\b", query, flags=re.IGNORECASE)
    return matched.group(0).upper() if matched else None


def _get_matching_latest_trace(
    request: AgentDiagnoseRequest,
) -> dict[str, Any] | None:
    trace = get_latest_agent_trace()
    if not isinstance(trace, dict):
        return None

    if trace.get("query") != request.query:
        return None

    trace_device_code = trace.get("device_code")
    if request.device_code and trace_device_code not in (None, request.device_code):
        return None

    return trace


def _extract_rag_sources(
    response: AgentDiagnoseResponse,
    trace: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    trace_results = trace.get("rag_results", []) if isinstance(trace, dict) else []
    if isinstance(trace_results, list) and trace_results:
        sources: list[dict[str, Any]] = []
        for item in trace_results:
            if not isinstance(item, dict) or not item.get("source"):
                continue
            source = {
                "source": item.get("source"),
                "filename": item.get("filename"),
                "chunk_id": item.get("chunk_id"),
                "chunk_index": item.get("chunk_index"),
                "distance": item.get("distance"),
                "content": item.get("content"),
            }
            if item.get("vector_score") is not None:
                source["vector_score"] = item.get("vector_score")
            if item.get("rerank_score") is not None:
                source["rerank_score"] = item.get("rerank_score")
            sources.append(source)
        return sources

    return [{"source": source} for source in response.sources]


def _extract_rag_sources_from_sources(
    sources: list[str],
    trace: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    trace_results = trace.get("rag_results", []) if isinstance(trace, dict) else []
    if isinstance(trace_results, list) and trace_results:
        sources: list[dict[str, Any]] = []
        for item in trace_results:
            if not isinstance(item, dict) or not item.get("source"):
                continue
            source = {
                "source": item.get("source"),
                "filename": item.get("filename"),
                "chunk_id": item.get("chunk_id"),
                "chunk_index": item.get("chunk_index"),
                "distance": item.get("distance"),
                "content": item.get("content"),
            }
            if item.get("vector_score") is not None:
                source["vector_score"] = item.get("vector_score")
            if item.get("rerank_score") is not None:
                source["rerank_score"] = item.get("rerank_score")
            sources.append(source)
        return sources

    return [{"source": source} for source in sources]


def _extract_primary_risk_alarm(
    response: MultiDeviceRiskResponse,
) -> str | None:
    for item in response.device_risks:
        if item.unresolved_alarms:
            return item.unresolved_alarms[0].alarm_code
    return None


def _calculate_diagnosis_confidence(
    response: AgentDiagnoseResponse,
    trace: dict[str, Any] | None,
) -> int:
    """Estimate evidence completeness for history review, not model accuracy."""

    score = 25
    if response.device is not None:
        score += 12
    if response.device_status is not None:
        score += 18
    if response.recent_alarms:
        score += 18
    if response.sources:
        score += 22

    llm_status = trace.get("llm_final_status") if isinstance(trace, dict) else None
    if isinstance(llm_status, dict) and llm_status.get("status") == "success":
        score += 5

    if response.device_status is None:
        score -= 8
    if not response.recent_alarms:
        score -= 8
    if not response.sources:
        score -= 10

    return max(15, min(82, score))
