from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePath
import re
from typing import Any

from app.domain.diagnosis.alarm_catalog import alarm_display_name, get_alarm_definition
from app.domain.diagnosis.models import (
    ConfirmedFact,
    DiagnosisCause,
    DiagnosisCitation,
    DiagnosisReportV2,
    DeviceRiskSummaryV2,
    FleetRiskReportV2,
    MaintenanceAction,
    VerificationStep,
)
from app.domain.diagnosis.parameter_rules import evaluate_runtime_parameters
from app.domain.diagnosis.risk_engine import calculate_risk_assessment


MOCK_OR_DEV_TEXT = re.compile(
    r"mock|draft generated|deterministic fallback|fallback|llm diagnosis unavailable",
    re.IGNORECASE,
)


def build_single_diagnosis_report(
    payload: Mapping[str, Any],
    trace: Mapping[str, Any] | None = None,
) -> DiagnosisReportV2:
    device = _as_mapping(payload.get("device"))
    runtime = _as_mapping(payload.get("device_status"))
    alarms = _as_mapping_list(payload.get("recent_alarms"))
    warnings = _as_string_list(payload.get("warnings"))
    sources = _as_string_list(payload.get("sources"))
    device_context = _device_context_from_trace(trace)
    observations = evaluate_runtime_parameters(_as_optional_string(device.get("device_type")), runtime)
    citations = _build_citations(trace, sources)
    generation_mode = _generation_mode(_as_string(payload.get("problem_summary")), warnings, trace)
    risk = calculate_risk_assessment(
        _as_string(payload.get("risk_level"), default="unknown"),
        observations=observations,
        alarm_levels=[
            _as_string(alarm.get("alarm_level"), default="unknown")
            for alarm in alarms
            if not bool(alarm.get("is_resolved"))
        ],
        is_online=_as_optional_bool(device.get("is_online")),
    )
    facts = _build_confirmed_facts(device, alarms, observations)
    evidence_refs = _evidence_refs(alarms, citations)
    causes = _build_causes(
        _as_string_list(payload.get("possible_causes")),
        alarms,
        observations,
        evidence_refs,
        citations,
    )
    action_plan = _build_actions(
        _as_string_list(payload.get("recommended_actions")),
        risk.level,
        alarms,
        observations,
        citations,
        generation_mode,
    )
    verification_steps = _build_verification_steps(causes, action_plan, observations)

    return DiagnosisReportV2(
        generation_mode=generation_mode,
        conclusion=_single_conclusion(payload, device, alarms, observations, generation_mode),
        risk=risk,
        confirmed_facts=facts,
        parameter_observations=observations,
        possible_causes=causes,
        verification_steps=verification_steps,
        action_plan=action_plan,
        citations=citations,
        data_gaps=_build_data_gaps(device, runtime, alarms, citations, causes),
        device_context_summary=_context_health_summary(device_context),
        risk_trend=_context_list(device_context, "risk_trend"),
        historical_cases=_context_list(device_context, "similar_cases"),
        maintenance_memory_refs=_context_list(device_context, "maintenance_memory"),
        diagnosis_session_id=_as_optional_string(
            _as_mapping(trace).get("diagnosis_session_id")
        ),
    )


def build_fleet_risk_report(
    payload: Mapping[str, Any],
    trace: Mapping[str, Any] | None = None,
) -> FleetRiskReportV2:
    warnings = _as_string_list(payload.get("warnings"))
    summary = _as_string(payload.get("summary"))
    generation_mode = _generation_mode(summary, warnings, trace)
    all_citations = _build_citations(trace, _as_string_list(payload.get("sources")))
    device_reports: list[DeviceRiskSummaryV2] = []

    for item in _as_mapping_list(payload.get("device_risks")):
        device = _as_mapping(item.get("device"))
        runtime = _as_mapping(item.get("latest_runtime_data"))
        alarms = _as_mapping_list(item.get("unresolved_alarms"))
        device_code = _as_string(device.get("device_code"), default="UNKNOWN")
        device_context = _device_context_for_device(trace, device_code)
        observations = evaluate_runtime_parameters(_as_optional_string(device.get("device_type")), runtime)
        citations = [
            citation
            for citation in all_citations
            if _citation_matches_device(citation, device_code, trace)
        ] or _citations_from_sources(_as_string_list(item.get("knowledge_sources")))
        risk = calculate_risk_assessment(
            _as_string(item.get("risk_level"), default="unknown"),
            observations=observations,
            alarm_levels=[_as_string(alarm.get("alarm_level"), default="unknown") for alarm in alarms],
            is_online=_as_optional_bool(device.get("is_online")),
        )
        evidence_refs = _evidence_refs(alarms, citations)
        causes = _build_causes(
            _as_string_list(item.get("reasons")),
            alarms,
            observations,
            evidence_refs,
            citations,
        )
        actions = _build_actions(
            _as_string_list(item.get("recommended_actions")),
            risk.level,
            alarms,
            observations,
            citations,
            generation_mode,
        )
        device_reports.append(
            DeviceRiskSummaryV2(
                device_code=device_code,
                device_name=_as_string(device.get("name"), default="未登记设备"),
                device_type=_as_string(device.get("device_type"), default="unknown"),
                risk=risk,
                confirmed_facts=_build_confirmed_facts(device, alarms, observations),
                parameter_observations=observations,
                possible_causes=causes,
                action_plan=actions,
                citations=citations,
                data_gaps=_build_data_gaps(device, runtime, alarms, citations, causes),
                device_context_summary=_context_health_summary(device_context),
                risk_trend=_context_list(device_context, "risk_trend"),
                historical_cases=_context_list(device_context, "similar_cases"),
                maintenance_memory_refs=_context_list(device_context, "maintenance_memory"),
            )
        )

    overall_risk = calculate_risk_assessment(
        _as_string(payload.get("overall_risk_level"), default="unknown")
    )
    data_gaps: list[str] = []
    if not device_reports:
        data_gaps.append("未返回可用于风险分析的设备数据。")
    if not all_citations and any(report.risk.level not in {"normal", "unknown"} for report in device_reports):
        data_gaps.append("存在风险设备，但本次没有获得可引用的维修知识来源。")

    return FleetRiskReportV2(
        generation_mode=generation_mode,
        summary=_fleet_summary(summary, device_reports, generation_mode),
        overall_risk=overall_risk,
        devices=device_reports,
        citations=all_citations,
        data_gaps=data_gaps,
        diagnosis_session_id=_as_optional_string(
            _as_mapping(trace).get("diagnosis_session_id")
        ),
    )


def _build_confirmed_facts(
    device: Mapping[str, Any],
    alarms: list[Mapping[str, Any]],
    observations: Sequence[Any],
) -> list[ConfirmedFact]:
    facts: list[ConfirmedFact] = []
    device_code = _as_optional_string(device.get("device_code"))
    if device_code:
        facts.append(
            ConfirmedFact(
                fact_id="device.identity",
                category="device",
                label="设备资产",
                value=f"{device_code} {_as_string(device.get('name'))}".strip(),
                status="info",
                source="device_tool",
            )
        )
        online = _as_optional_bool(device.get("is_online"))
        facts.append(
            ConfirmedFact(
                fact_id="device.online_status",
                category="device",
                label="在线状态",
                value="在线" if online else "离线或未知",
                status="normal" if online else "warning",
                source="device_tool",
            )
        )

    for observation in observations:
        facts.append(
            ConfirmedFact(
                fact_id=f"runtime.{observation.parameter}",
                category="runtime",
                label=observation.label,
                value=f"{observation.value:g}{observation.unit}",
                status=observation.status,
                source="device_runtime_data",
            )
        )

    for index, alarm in enumerate(alarms):
        code = _as_string(alarm.get("alarm_code"), default="UNKNOWN")
        resolved = bool(alarm.get("is_resolved")) or _as_string(alarm.get("status")).lower() == "resolved"
        facts.append(
            ConfirmedFact(
                fact_id=f"alarm.{code}.{index}",
                category="alarm",
                label=f"{code} {alarm_display_name(code, _as_optional_string(alarm.get('message')))}",
                value="已处理" if resolved else "待处理",
                status="normal" if resolved else _fact_status(alarm.get("alarm_level") or alarm.get("level")),
                source="device_alarm_records",
            )
        )
    return facts


def _build_causes(
    legacy_causes: list[str],
    alarms: list[Mapping[str, Any]],
    observations: Sequence[Any],
    evidence_refs: list[str],
    citations: list[DiagnosisCitation],
) -> list[DiagnosisCause]:
    causes: list[DiagnosisCause] = []
    confidence = "medium" if citations else "low"
    for cause in legacy_causes:
        normalized = _business_text(cause)
        if not normalized or MOCK_OR_DEV_TEXT.search(normalized):
            continue
        causes.append(
            DiagnosisCause(
                title=_cause_title(normalized),
                description=normalized,
                confidence=confidence,
                evidence_refs=evidence_refs,
                verification_method=_verification_method(normalized),
            )
        )

    if causes:
        return causes[:10]

    generated: list[DiagnosisCause] = []
    for alarm in alarms:
        if bool(alarm.get("is_resolved")) or _as_string(alarm.get("status")).lower() == "resolved":
            continue
        code = _as_string(alarm.get("alarm_code"))
        name = alarm_display_name(code, _as_optional_string(alarm.get("message")))
        description = _alarm_cause_description(code, name, citations)
        generated.append(
            DiagnosisCause(
                title=f"{code} {name}相关风险",
                description=description,
                confidence="medium" if citations else "low",
                evidence_refs=evidence_refs,
                verification_method=_verification_method(description),
            )
        )

    for observation in observations:
        if observation.status not in {"warning", "critical"}:
            continue
        generated.append(
            DiagnosisCause(
                title=f"{observation.label}异常风险",
                description=f"{observation.label}当前值为 {observation.value:g}{observation.unit}，{observation.explanation}建议结合现场负载、环境和历史趋势确认原因。",
                confidence="medium" if citations else "low",
                evidence_refs=evidence_refs,
                verification_method=_verification_method(observation.label),
            )
        )

    return _dedupe_causes(generated)[:10]


def _build_actions(
    legacy_actions: list[str],
    risk_level: str,
    alarms: list[Mapping[str, Any]],
    observations: Sequence[Any],
    citations: list[DiagnosisCitation],
    generation_mode: str,
) -> list[MaintenanceAction]:
    actions = [
        _business_text(action)
        for action in legacy_actions
        if action.strip() and not MOCK_OR_DEV_TEXT.search(action)
    ]
    if generation_mode in {"mock", "fallback"} or not actions:
        actions = _deterministic_actions(risk_level, alarms, observations, bool(citations))

    evidence_refs = _evidence_refs(alarms, citations)
    return [
        MaintenanceAction(
            order=index,
            priority=_action_priority(index, risk_level),
            title=_action_title(action, index, risk_level),
            description=action,
            safety_required=risk_level in {"high", "critical"} and index == 1,
            evidence_refs=evidence_refs,
        )
        for index, action in enumerate(_dedupe(actions)[:10], start=1)
    ]


def _build_verification_steps(
    causes: list[DiagnosisCause],
    actions: list[MaintenanceAction],
    observations: Sequence[Any],
) -> list[VerificationStep]:
    descriptions = [cause.verification_method for cause in causes]
    descriptions.extend(
        f"复核{observation.label}历史趋势，确认异常是否持续存在。"
        for observation in observations
        if observation.status in {"warning", "critical"}
    )
    descriptions.extend(action.description for action in actions[:2])
    unique = _dedupe(descriptions)[:5] or ["现场复核设备状态、报警记录和运行参数，补充人工检查结论。"]
    return [
        VerificationStep(
            order=index,
            title=f"现场验证 {index}",
            description=description,
            safety_note="涉及带电、旋转部件或高温部位时，必须执行停机、挂牌和安全隔离要求。"
            if index == 1
            else None,
        )
        for index, description in enumerate(unique, start=1)
    ]


def _build_citations(trace: Mapping[str, Any] | None, fallback_sources: list[str]) -> list[DiagnosisCitation]:
    rag_results = _as_mapping_list(trace.get("rag_results")) if trace else []
    citations: list[DiagnosisCitation] = []
    for index, result in enumerate(rag_results, start=1):
        source = _as_string(result.get("source"))
        if not source:
            continue
        citations.append(
            DiagnosisCitation(
                citation_id=f"knowledge.{index}",
                source=source,
                title=_document_title(_as_optional_string(result.get("filename")) or source),
                excerpt=_clean_excerpt(_as_optional_string(result.get("content"))),
                document_id=_as_optional_int(result.get("document_id")),
                chunk_id=_as_optional_int(result.get("chunk_id")),
                chunk_index=_as_optional_int(result.get("chunk_index")),
                distance=_as_optional_float(result.get("distance")),
            )
        )
    return _dedupe_citations(citations) if citations else _citations_from_sources(fallback_sources)


def _citations_from_sources(sources: list[str]) -> list[DiagnosisCitation]:
    return [
        DiagnosisCitation(citation_id=f"knowledge.{index}", source=source, title=_document_title(source))
        for index, source in enumerate(_dedupe(sources), start=1)
    ]


def _generation_mode(summary: str, warnings: list[str], trace: Mapping[str, Any] | None) -> str:
    combined = " ".join([summary, *warnings])
    if MOCK_OR_DEV_TEXT.search(combined):
        return "mock" if "mock" in combined.lower() else "fallback"
    llm_status = _as_mapping(trace.get("llm_final_status")) if trace else {}
    status = _as_string(llm_status.get("status"))
    if status == "mock":
        return "mock"
    if status == "fallback":
        return "fallback"
    if status == "success":
        return "llm"
    return "deterministic"


def _single_conclusion(
    payload: Mapping[str, Any],
    device: Mapping[str, Any],
    alarms: list[Mapping[str, Any]],
    observations: Sequence[Any],
    generation_mode: str,
) -> str:
    summary = _business_text(_as_string(payload.get("problem_summary")))
    if generation_mode not in {"mock", "fallback"} and summary and not MOCK_OR_DEV_TEXT.search(summary):
        return summary

    device_code = _as_string(device.get("device_code"), default="当前设备")
    unresolved = [
        alarm
        for alarm in alarms
        if not bool(alarm.get("is_resolved")) and _as_string(alarm.get("status")).lower() != "resolved"
    ]
    abnormal_parameters = [
        f"{observation.label}{'超过安全范围' if observation.status == 'critical' else '接近安全阈值'}"
        for observation in observations
        if observation.status in {"warning", "critical"}
    ]
    if unresolved:
        labels = [
            f"{_as_string(alarm.get('alarm_code'))} {alarm_display_name(_as_string(alarm.get('alarm_code')), _as_optional_string(alarm.get('message')))}"
            for alarm in unresolved
        ]
        details = "，同时检测到" + "、".join(abnormal_parameters) if abnormal_parameters else ""
        return f"{device_code} 当前存在{'、'.join(labels)}待处理报警{details}。系统已基于设备事实、报警记录和维修知识生成辅助诊断，请结合现场情况确认。"
    if abnormal_parameters:
        return f"{device_code} 当前未发现待处理报警，但{ '、'.join(abnormal_parameters) }。建议补充现场巡检结果后复核。"
    return f"{device_code} 当前未发现明确报警或参数越限，建议结合用户描述继续确认现场状态。"


def _fleet_summary(
    summary: str,
    devices: list[DeviceRiskSummaryV2],
    generation_mode: str,
) -> str:
    normalized = _business_text(summary)
    if generation_mode not in {"mock", "fallback"} and normalized and not MOCK_OR_DEV_TEXT.search(normalized):
        return normalized
    total = len(devices)
    risky = sum(item.risk.level not in {"normal", "unknown"} for item in devices)
    high = sum(item.risk.level in {"high", "critical"} for item in devices)
    if total == 0:
        return "本次未获得可用于分析的设备数据，无法形成多设备风险结论。"
    return f"本次共分析 {total} 台设备，其中 {risky} 台存在风险信号，{high} 台需要优先现场复核。"


def _build_data_gaps(
    device: Mapping[str, Any],
    runtime: Mapping[str, Any],
    alarms: list[Mapping[str, Any]],
    citations: list[DiagnosisCitation],
    causes: list[DiagnosisCause],
) -> list[str]:
    gaps: list[str] = []
    if not device:
        gaps.append("缺少设备基础信息。")
    if not runtime:
        gaps.append("缺少最新运行参数。")
    if not alarms:
        gaps.append("本次未返回报警记录。")
    if not citations:
        gaps.append("未找到可引用的维修知识来源。")
    if not causes:
        gaps.append("当前证据不足以形成明确原因，需要现场验证。")
    return gaps


def _device_context_from_trace(trace: Mapping[str, Any] | None) -> Mapping[str, Any]:
    trace_mapping = _as_mapping(trace)
    return _as_mapping(trace_mapping.get("device_context"))


def _device_context_for_device(
    trace: Mapping[str, Any] | None,
    device_code: str,
) -> Mapping[str, Any]:
    context = _device_context_from_trace(trace)
    device = _as_mapping(context.get("device"))
    if _as_string(device.get("device_code")) == device_code:
        return context
    return {}


def _context_health_summary(context: Mapping[str, Any]) -> dict | None:
    summary = _as_mapping(context.get("health_summary"))
    if not summary:
        return None
    return {
        "current_risk_level": summary.get("current_risk_level"),
        "current_risk_score": summary.get("current_risk_score"),
        "unresolved_alarm_count": summary.get("unresolved_alarm_count"),
        "historical_alarm_count": summary.get("historical_alarm_count"),
        "diagnosis_count": summary.get("diagnosis_count"),
        "maintenance_record_count": summary.get("maintenance_record_count"),
        "abnormal_parameters": summary.get("abnormal_parameters") or [],
        "trend": summary.get("trend"),
    }


def _context_list(context: Mapping[str, Any], key: str) -> list[dict]:
    return [
        dict(item)
        for item in _as_mapping_list(context.get(key))
        if isinstance(item, Mapping)
    ][:10]


def _deterministic_actions(
    risk_level: str,
    alarms: list[Mapping[str, Any]],
    observations: Sequence[Any],
    has_citations: bool,
) -> list[str]:
    actions: list[str] = []
    if risk_level in {"high", "critical"}:
        actions.append("优先处理高风险设备，必要时降低负载或安排安全停机检查。")

    for alarm in alarms:
        if bool(alarm.get("is_resolved")) or _as_string(alarm.get("status")).lower() == "resolved":
            continue
        code = _as_string(alarm.get("alarm_code"))
        definition = get_alarm_definition(code)
        if definition:
            actions.append(definition.safety_guidance)
        actions.append(f"复核 {code} {alarm_display_name(code, _as_optional_string(alarm.get('message')))} 报警记录，确认报警发生时间、持续时间和现场状态。")

    for observation in observations:
        if observation.status == "critical":
            actions.append(f"立即复核{observation.label}读数，确认是否超过安全范围并检查相关部件。")
        elif observation.status == "warning":
            actions.append(f"跟踪{observation.label}趋势，确认是否继续接近安全阈值。")

    if has_citations:
        actions.append("按照引用维修资料中的检查顺序逐项验证，并记录检查结果。")
    else:
        actions.append("补充设备手册、历史维修记录或现场检查数据后，再确认最终维修方案。")

    if not actions:
        actions.append("保持日常监控，记录后续运行趋势。")
    actions.append("处理完成后关闭对应报警，并将根因、处理过程和结果沉淀为维修案例。")
    return _dedupe(actions)


def _business_text(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return ""
    lower = normalized.lower()
    if "mock diagnosis draft" in lower:
        return "系统已根据设备运行数据、报警记录和维修资料生成辅助诊断结果，请结合现场情况确认。"
    if "please combine equipment data" in lower:
        return "建议现场检查设备运行状态，并结合报警记录和维修资料确认异常原因。"
    if "prioritize unresolved alarms" in lower:
        return "优先处理高风险设备中的未关闭报警，安排现场检查并确认异常状态。"
    if "schedule inspection" in lower:
        return "安排中风险设备巡检，确认运行参数和异常原因。"
    if "keep routine monitoring" in lower:
        return "当前设备运行参数正常，继续保持日常监控。"
    analyzed = re.match(r"Analyzed\s+(\d+)\s+devices?;\s*(\d+)\s+devices?\s+have\s+risk\s+signals?\.?", normalized, re.IGNORECASE)
    if analyzed:
        return f"本次共分析 {analyzed.group(1)} 台设备，其中 {analyzed.group(2)} 台存在风险信号。"
    reason = re.match(r"(DEV-\d+)\s*:\s*(\d+)\s+unresolved alarms?(?:,\s*(.*))?", normalized, re.IGNORECASE)
    if reason:
        detail = _translate_reason_detail(reason.group(3) or "")
        return f"设备 {reason.group(1)} 当前存在 {reason.group(2)} 条未处理报警{detail}，建议结合运行参数和现场检查确认异常原因。"
    return normalized


def _translate_reason_detail(detail: str) -> str:
    lower = detail.lower()
    if not detail:
        return ""
    if "temperature exceeds safe range" in lower:
        return "，并检测到温度超过安全范围"
    if "temperature is near threshold" in lower:
        return "，且温度接近安全阈值"
    if "vibration" in lower:
        return "，并检测到振动状态异常"
    if "current" in lower:
        return "，并检测到电流状态异常"
    if "communication" in lower:
        return "，可能存在通信链路异常"
    return ""


def _alarm_cause_description(code: str, name: str, citations: list[DiagnosisCitation]) -> str:
    cited = "，并已有企业维修资料可用于排查" if citations else "，但当前缺少可引用的维修资料"
    if code == "E101":
        return f"{code} {name}通常需要重点关注散热、环境温度、负载变化和温度传感器状态{cited}。"
    if code == "E201":
        return f"{code} {name}通常需要重点检查轴承、联轴器、安装基础、转轴偏移和机械松动{cited}。"
    if code == "E203":
        return f"{code} {name}可能与电流偏高、负载异常、轴承阻力或控制回路异常有关{cited}。"
    if code == "E404":
        return f"{code} {name}通常需要检查通信线缆、网关、控制器地址、网络链路和模块日志{cited}。"
    return f"{code} {name}仍处于待处理状态，需要结合设备参数和现场工况确认具体原因。"


def _evidence_refs(alarms: list[Mapping[str, Any]], citations: list[DiagnosisCitation]) -> list[str]:
    refs = [f"alarm:{_as_string(alarm.get('alarm_code'))}" for alarm in alarms if _as_string(alarm.get("alarm_code"))]
    refs.extend(citation.citation_id for citation in citations)
    return _dedupe(refs)


def _citation_matches_device(citation: DiagnosisCitation, device_code: str, trace: Mapping[str, Any] | None) -> bool:
    if not trace:
        return False
    for result in _as_mapping_list(trace.get("rag_results")):
        if _as_string(result.get("source")) != citation.source:
            continue
        result_device = _as_optional_string(result.get("device_code"))
        return result_device in {None, device_code}
    return False


def _document_title(source: str) -> str:
    filename = PurePath(source.split("#", maxsplit=1)[0]).name
    normalized = filename.lower()
    for code in ("E101", "E201", "E203", "E404"):
        if code.lower() in normalized:
            return f"{code} {alarm_display_name(code)}维护手册"
    stem = re.sub(r"[_-]+", " ", PurePath(filename).stem).strip()
    return stem or "企业设备维修资料"


def _clean_excerpt(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"```[\s\S]*?```", "", value)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = " ".join(text.split())
    return text[:600] or None


def _cause_title(cause: str) -> str:
    title = re.split(r"[。；;，,]", cause.strip(), maxsplit=1)[0]
    return title[:60] or "待验证原因"


def _verification_method(cause: str) -> str:
    lowered = cause.lower()
    if "温度" in cause or "散热" in cause or "temperature" in lowered:
        return "检查温度趋势、散热风道、风扇状态、环境温度和设备负载。"
    if "振动" in cause or "轴承" in cause or "vibration" in lowered:
        return "测量振动值，检查轴承、联轴器、底座和机械连接。"
    if "通信" in cause or "communication" in lowered:
        return "检查通信线缆、设备地址、网关日志、控制器状态和交换机端口。"
    if "电流" in cause or "过载" in cause or "current" in lowered:
        return "核对电流趋势、设备负载和机械传动阻力。"
    return "结合设备运行参数、报警记录和现场状态逐项验证。"


def _action_title(action: str, order: int, risk_level: str) -> str:
    if risk_level in {"high", "critical"} and order == 1:
        return "立即安全处置"
    if order == 1:
        return "现场初步复核"
    if order == 2:
        return "定位异常原因"
    if order == 3:
        return "执行维修处理"
    return "记录与持续跟踪"


def _action_priority(order: int, risk_level: str) -> str:
    if risk_level in {"high", "critical"} and order <= 2:
        return "immediate"
    if risk_level == "medium" and order == 1:
        return "immediate"
    if risk_level in {"normal", "low"}:
        return "observe"
    return "planned"


def _fact_status(level: object) -> str:
    normalized = _as_string(level).lower()
    if normalized in {"critical", "high"}:
        return "critical"
    if normalized in {"medium", "low"}:
        return "warning"
    return "unknown"


def _dedupe_citations(citations: list[DiagnosisCitation]) -> list[DiagnosisCitation]:
    seen: set[str] = set()
    result: list[DiagnosisCitation] = []
    for citation in citations:
        if citation.source in seen:
            continue
        seen.add(citation.source)
        result.append(citation)
    return result


def _dedupe_causes(causes: list[DiagnosisCause]) -> list[DiagnosisCause]:
    seen: set[str] = set()
    result: list[DiagnosisCause] = []
    for cause in causes:
        key = cause.title
        if key in seen:
            continue
        seen.add(key)
        result.append(cause)
    return result


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_string(value: object, default: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _as_optional_string(value: object) -> str | None:
    result = _as_string(value)
    return result or None


def _as_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
