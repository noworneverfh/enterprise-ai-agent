from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent import trace as agent_trace
from app.agent.tools import (
    run_get_device_alarms_tool,
    run_get_device_status_tool,
    run_search_knowledge_tool,
)
from app.agent.workflow import DISCLAIMER
from app.llm.base import LLMMessage, LLMProvider
from app.schemas.agent import (
    DeviceAlarmsToolInput,
    DeviceAlarmsToolResult,
    DeviceRiskItem,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    MultiDeviceRiskDraft,
    MultiDeviceRiskRequest,
    MultiDeviceRiskResponse,
    RiskLevel,
    ToolAlarmRecord,
    ToolDeviceAlarm,
)
from app.services import device as device_service


logger = logging.getLogger(__name__)

RISK_LEVEL_ORDER = {
    "unknown": 0,
    "normal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}
ALARM_LEVEL_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
SAFE_LIMITS = {
    "temperature": 60.0,
    "voltage_min": 200.0,
    "voltage_max": 245.0,
    "current": 10.0,
    "vibration": 0.4,
}
NEAR_LIMIT_RATIO = 0.85
DEVICE_CODE_PATTERN = re.compile(r"\bDEV-\d+\b", re.IGNORECASE)


def run_multi_device_risk_analysis(
    db: Session,
    request: MultiDeviceRiskRequest,
    llm_provider: LLMProvider,
) -> MultiDeviceRiskResponse:
    """Compatibility entry backed by the enterprise DiagnosisOrchestrator."""

    from app.agent.orchestrator import DiagnosisOrchestrator

    orchestrator = DiagnosisOrchestrator(db=db, llm_provider=llm_provider)
    return orchestrator.run_fleet(request)


def _knowledge_query(alarm: ToolDeviceAlarm) -> str:
    return f"{alarm.alarm_code} {alarm.alarm_name} handling steps"


def _generate_risk_draft(
    request: MultiDeviceRiskRequest,
    device_risks: list[DeviceRiskItem],
    sources: list[str],
    knowledge_evidence: list[dict[str, Any]],
    llm_provider: LLMProvider,
) -> tuple[MultiDeviceRiskDraft, bool]:
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are an enterprise industrial device risk analysis assistant. "
                "Generate the risk report only from the provided device status, alarm records, "
                "and knowledge_evidence. The knowledge_evidence contains RAG search results "
                "grouped by device_code and alarm_code. Do not invent devices, alarms, metrics, "
                "or knowledge sources. Output only a valid JSON object with fields: "
                "summary, overall_risk_level, key_findings, recommended_actions, warnings. "
                "overall_risk_level must be one of normal, low, medium, high, critical, unknown."
            ),
        ),
        LLMMessage(
            role="user",
            content=json.dumps(
                {
                    "query": request.query,
                    "device_risks": [
                        _device_risk_payload(item) for item in device_risks
                    ],
                    "knowledge_evidence": knowledge_evidence,
                    "sources": sources,
                },
                ensure_ascii=False,
            ),
        ),
    ]

    try:
        return llm_provider.complete_structured(messages, MultiDeviceRiskDraft), True
    except Exception:
        logger.exception("Multi-device risk LLM generation failed.")
        agent_trace.record_llm_final_status(
            status="fallback",
            fallback_reason="risk_llm_failed",
        )
        return _fallback_risk_draft(device_risks), False


def _fallback_risk_draft(
    device_risks: list[DeviceRiskItem],
) -> MultiDeviceRiskDraft:
    risky_items = [item for item in device_risks if item.risk_level != "normal"]
    return MultiDeviceRiskDraft(
        summary=f"本次共分析 {len(device_risks)} 台设备，其中 {len(risky_items)} 台存在风险信号。",
        overall_risk_level=_max_risk_level([item.risk_level for item in device_risks]),
        key_findings=[
            f"{item.device.device_code}: {', '.join(item.reasons[:2]) or 'parameters normal'}"
            for item in device_risks[:8]
        ],
        recommended_actions=[
            "优先处理高风险设备中的未关闭报警，建议安排现场检查并确认异常状态。",
            "安排中风险设备巡检，确认设备运行参数和异常原因。",
            "当前设备运行参数正常，继续保持日常监控。",
        ],
        warnings=["智能推理服务暂时不可用，已生成确定性风险汇总。"],
    )


def _build_device_risk_item(
    device_code: str,
    status_result: DeviceStatusToolResult,
    alarms_result: DeviceAlarmsToolResult | None,
    knowledge_by_device_alarm: dict[tuple[str, str], KnowledgeSearchToolResult],
) -> DeviceRiskItem:
    assert status_result.device is not None
    alarms = list(status_result.recent_alarms)
    reasons: list[str] = []
    knowledge_sources: list[str] = []
    actions: list[str] = []

    if alarms_result is not None and alarms_result.ok and not alarms:
        alarms = _alarms_from_alarm_tool(device_code, alarms_result, status_result)
    alarms = sorted(alarms, key=lambda item: item.alarm_code)

    parameter_status = _evaluate_parameters(status_result)

    if alarms:
        reasons.append(f"{len(alarms)} 条未处理报警")
        actions.append("确认报警是否仍然存在，并优先处理未关闭报警。")
    for alarm in alarms:
        knowledge_result = knowledge_by_device_alarm.get((device_code, alarm.alarm_code))
        if knowledge_result is not None and knowledge_result.results:
            knowledge_sources.extend(result.source for result in knowledge_result.results)
            actions.append(f"Use {alarm.alarm_code} knowledge base evidence for inspection.")
        else:
            reasons.append(f"{alarm.alarm_code} has no matching knowledge evidence")

    if parameter_status["exceeded"]:
        reasons.extend(parameter_status["reasons"])
        actions.append("Verify exceeded parameters immediately; reduce load or stop the device if needed.")
    elif parameter_status["near_limit"]:
        reasons.extend(parameter_status["reasons"])
        actions.append("Schedule inspection and monitor parameters near thresholds.")

    if not status_result.device.is_online:
        reasons.append("device offline")
        actions.append("Check device network status and on-site power supply.")

    risk_level = _classify_device_risk(
        alarms=alarms,
        parameter_exceeded=parameter_status["exceeded"],
        parameter_near_limit=parameter_status["near_limit"],
    )
    risk_score = _risk_score(risk_level, alarms, parameter_status)
    if risk_level == "normal":
        reasons.append("无报警且运行参数正常")
        actions.append("继续保持日常监控。")

    return DeviceRiskItem(
        device=status_result.device,
        latest_runtime_data=status_result.latest_runtime_data,
        unresolved_alarms=alarms,
        risk_level=risk_level,
        risk_score=risk_score,
        reasons=_dedupe(reasons),
        knowledge_sources=_dedupe(knowledge_sources),
        recommended_actions=_dedupe(actions),
    )


def _alarms_from_alarm_tool(
    device_code: str,
    alarms_result: DeviceAlarmsToolResult,
    status_result: DeviceStatusToolResult,
) -> list[ToolAlarmRecord]:
    device = status_result.device
    if device is None:
        return []

    return [
        ToolAlarmRecord(
            id=index + 1,
            device_id=device.id,
            alarm_code=alarm.alarm_code,
            alarm_level=alarm.level,
            message=alarm.alarm_name,
            is_resolved=alarm.status == "resolved",
            occurred_at=alarm.created_at,
            resolved_at=None,
            created_at=alarm.created_at,
        )
        for index, alarm in enumerate(alarms_result.alarms)
        if alarm.device_id == device_code
    ]


def _classify_device_risk(
    alarms: list[ToolAlarmRecord],
    parameter_exceeded: bool,
    parameter_near_limit: bool,
) -> RiskLevel:
    alarm_level = _max_alarm_level(alarms)
    if alarm_level in {"high", "critical"} or parameter_exceeded:
        return "high"
    if alarms or parameter_near_limit:
        return "medium"
    return "normal"


def _max_alarm_level(alarms: list[ToolAlarmRecord]) -> str | None:
    if not alarms:
        return None
    return max(
        (alarm.alarm_level.lower() for alarm in alarms),
        key=lambda level: ALARM_LEVEL_ORDER.get(level, 0),
    )


def _evaluate_parameters(status_result: DeviceStatusToolResult) -> dict[str, Any]:
    runtime = status_result.latest_runtime_data
    if runtime is None:
        return {
            "exceeded": False,
            "near_limit": True,
            "reasons": ["missing runtime data"],
        }

    exceeded = False
    near_limit = False
    reasons: list[str] = []

    if runtime.temperature is not None:
        if runtime.temperature > SAFE_LIMITS["temperature"]:
            exceeded = True
            reasons.append("temperature exceeds safe range")
        elif runtime.temperature >= SAFE_LIMITS["temperature"] * NEAR_LIMIT_RATIO:
            near_limit = True
            reasons.append("temperature is near threshold")

    if runtime.current is not None:
        if runtime.current > SAFE_LIMITS["current"]:
            exceeded = True
            reasons.append("current exceeds safe range")
        elif runtime.current >= SAFE_LIMITS["current"] * NEAR_LIMIT_RATIO:
            near_limit = True
            reasons.append("current is near threshold")

    if runtime.vibration is not None:
        if runtime.vibration > SAFE_LIMITS["vibration"]:
            exceeded = True
            reasons.append("vibration exceeds safe range")
        elif runtime.vibration >= SAFE_LIMITS["vibration"] * NEAR_LIMIT_RATIO:
            near_limit = True
            reasons.append("vibration is near threshold")

    if runtime.voltage is not None and (
        runtime.voltage < SAFE_LIMITS["voltage_min"]
        or runtime.voltage > SAFE_LIMITS["voltage_max"]
    ):
        exceeded = True
        reasons.append("voltage exceeds safe range")

    if runtime.status.lower() not in {"normal", "ok"}:
        near_limit = True
        reasons.append(f"runtime status is {runtime.status}")

    return {
        "exceeded": exceeded,
        "near_limit": near_limit,
        "reasons": reasons,
    }


def _risk_score(
    risk_level: str,
    alarms: list[ToolAlarmRecord],
    parameter_status: dict[str, Any],
) -> int:
    base = {
        "normal": 0,
        "low": 25,
        "medium": 55,
        "high": 80,
        "critical": 95,
        "unknown": 10,
    }[risk_level]
    base += min(10, len(alarms) * 3)
    alarm_level = _max_alarm_level(alarms)
    base += {
        "low": 1,
        "medium": 3,
        "high": 6,
        "critical": 10,
        None: 0,
    }.get(alarm_level, 0)
    if parameter_status["exceeded"]:
        base += 8
    elif parameter_status["near_limit"]:
        base += 4
    return min(100, base)


def _device_risk_payload(item: DeviceRiskItem) -> dict[str, Any]:
    runtime = item.latest_runtime_data
    return {
        "device_code": item.device.device_code,
        "device_type": item.device.device_type,
        "location": item.device.location,
        "is_online": item.device.is_online,
        "runtime_status": runtime.status if runtime else None,
        "parameters": (
            {
                "temperature": runtime.temperature,
                "voltage": runtime.voltage,
                "current": runtime.current,
                "vibration": runtime.vibration,
            }
            if runtime
            else None
        ),
        "alarms": [
            {
                "alarm_code": alarm.alarm_code,
                "alarm_level": alarm.alarm_level,
                "message": alarm.message,
            }
            for alarm in item.unresolved_alarms
        ],
        "risk_level": item.risk_level,
        "risk_score": item.risk_score,
        "reasons": item.reasons,
        "knowledge_sources": item.knowledge_sources,
        "recommended_actions": item.recommended_actions,
    }


def _knowledge_evidence_payload(
    knowledge_by_device_alarm: dict[tuple[str, str], KnowledgeSearchToolResult],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for (device_code, alarm_code), knowledge_result in knowledge_by_device_alarm.items():
        evidence.append(
            {
                "device_code": device_code,
                "alarm_code": alarm_code,
                "results": [
                    {
                        "filename": result.filename,
                        "source": result.source,
                        "distance": result.distance,
                        "content": result.content,
                        "chunk_id": result.chunk_id,
                        "chunk_index": result.chunk_index,
                    }
                    for result in knowledge_result.results
                ],
                "warnings": knowledge_result.warnings,
            }
        )
    return evidence


def _data_quality_warnings(query: str, device_codes: list[str]) -> list[str]:
    requested_codes = {
        match.group(0).upper() for match in DEVICE_CODE_PATTERN.finditer(query)
    }
    missing_codes = sorted(requested_codes - set(device_codes))
    return [
        f"Data quality warning: requested device does not exist and is excluded from risk ranking: {device_code}"
        for device_code in missing_codes
    ]


def _calculate_confidence(
    device_risks: list[DeviceRiskItem],
    sources: list[str],
    llm_success: bool,
) -> int:
    score = 30
    if device_risks:
        score += 20
    if any(item.latest_runtime_data is not None for item in device_risks):
        score += 20
    if any(item.unresolved_alarms for item in device_risks):
        score += 15
    if sources:
        score += 10
    if llm_success:
        score += 5
    return max(20, min(85, score))


def _max_risk_level(levels: list[str]) -> RiskLevel:
    if not levels:
        return "unknown"
    return max(levels, key=lambda level: RISK_LEVEL_ORDER.get(level, 0))  # type: ignore[return-value]


def _record_model_tool_result(
    tool_name: str,
    result: BaseModel,
    trace_context: dict[str, Any] | None = None,
) -> None:
    _record_tool_result(
        tool_name,
        True,
        result.model_dump(mode="json"),
        trace_context=trace_context,
    )


def _record_tool_result(
    tool_name: str,
    success: bool,
    result: dict[str, Any],
    error: str | None = None,
    trace_context: dict[str, Any] | None = None,
) -> None:
    payload = dict(result)
    if trace_context:
        payload["_trace"] = trace_context
    agent_trace.record_tool_result(
        {
            "tool_name": tool_name,
            "success": success,
            "result": payload,
            "error": error,
        }
    )


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
