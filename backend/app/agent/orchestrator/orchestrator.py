from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from app.agent import trace as agent_trace
from app.conversation import service as conversation_service
from app.conversation.models import Conversation, Message
from app.context.device_context import build_device_context
from app.context.knowledge_context import build_context_aware_queries
from app.context.schemas import DeviceContext
from app.domain.diagnosis.alarm_catalog import alarm_display_name
from app.domain.diagnosis.parameter_rules import evaluate_runtime_parameters
from app.llm.base import LLMMessage, LLMProvider
from app.schemas.agent import (
    AgentDiagnoseRequest,
    AgentDiagnoseResponse,
    AgentDiagnosisDraft,
    DeviceAlarmsToolResult,
    DeviceRiskItem,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolResult,
    MultiDeviceRiskDraft,
    MultiDeviceRiskRequest,
    MultiDeviceRiskResponse,
    RiskLevel,
    ToolAlarmRecord,
)

from .context import (
    DiagnosisEvidenceBundle,
    DiagnosisOrchestratorContext,
    DiagnosisTrace,
    EvidenceItem,
    GenerationMetadata,
    now_utc,
)
from .executor import ToolExecutionEngine
from .planner import IntentPlanner, ToolPlan


logger = logging.getLogger(__name__)

DISCLAIMER = (
    "本诊断结果由设备数据和知识库信息辅助生成，仅供排查参考。涉及"
    "高温、电气、机械或安全风险时，请停止设备并由专业人员现场确认。"
)
LLM_UNAVAILABLE_WARNING = "智能诊断服务暂时不可用，已根据设备数据和知识库信息生成保守结果。"
RISK_ORDER = {
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
PARAMETER_CONCERN_KEYWORDS = {
    "temperature": ("\u6e29\u5ea6", "\u8fc7\u70ed", "\u5347\u6e29", "\u9ad8\u6e29"),
    "vibration": ("\u632f\u52a8", "\u9707\u52a8"),
    "current": ("\u7535\u6d41", "\u8fc7\u8f7d"),
    "voltage": ("\u7535\u538b",),
    "communication": ("\u901a\u4fe1", "\u901a\u8baf"),
}
ALARM_PARAMETER_HINTS = {
    "E101": {"temperature"},
    "E201": {"vibration"},
    "E203": {"current", "vibration"},
    "E404": {"communication"},
}
PARAMETER_FAULT_HINTS = {
    "temperature": "E101",
    "vibration": "E201",
    "current": "E203",
    "communication": "E404",
}


class DiagnosisOrchestrator:
    """Unified enterprise orchestration for diagnosis and fleet risk analysis."""

    def __init__(
        self,
        db: Session,
        llm_provider: LLMProvider,
        planner: IntentPlanner | None = None,
    ) -> None:
        self.db = db
        self.llm_provider = llm_provider
        self.planner = planner or IntentPlanner()
        self.engine = ToolExecutionEngine(db)

    def run_single(
        self,
        request: AgentDiagnoseRequest,
        *,
        mode: str = "runtime",
    ) -> AgentDiagnoseResponse:
        conversation = _get_request_conversation(self.db, request)
        history_messages = _get_request_history(self.db, request, conversation)
        _save_user_message(self.db, conversation, request)

        planning_request = request.model_copy(
            update={"query": _history_augmented_query(request.query, history_messages)}
        )
        plan = self.planner.plan_single(planning_request)
        if mode == "workflow":
            plan = replace(
                plan,
                tool_names=[
                    tool_name
                    for tool_name in plan.tool_names
                    if tool_name != "get_device_alarms"
                ],
            )
        if plan.mode == "small_talk" and request.include_knowledge and _history_fault_codes(history_messages):
            plan = replace(
                plan,
                mode="single_device",
                tool_names=["search_knowledge"],
                reason="Conversation history contains fault context for a follow-up query.",
                fault_codes=_history_fault_codes(history_messages),
            )
        context = self._start_context(
            mode="runtime" if mode == "runtime" else "workflow",
            query=request.query,
            device_code=plan.device_code,
            planned_tools=plan.tool_names,
            reason=plan.reason,
        )
        if plan.device_code:
            context.device_context = self._load_device_context(plan.device_code)
            self._collect_device_context_evidence(context)

        if plan.mode == "small_talk":
            response = AgentDiagnoseResponse(
                problem_summary="当前问题没有包含设备编号、报警码或故障现象，请补充诊断对象。",
                risk_level="unknown",
                possible_causes=[],
                recommended_actions=[
                    "请提供设备编号。",
                    "请提供报警码或故障现象。",
                ],
                sources=[],
                tools_used=[],
                warnings=[],
                disclaimer=DISCLAIMER,
            )
            _save_assistant_message(self.db, conversation, response)
            return response

        self._execute_single_plan(context, request, plan, planning_request.query)
        draft, metadata = self._generate_single_draft(context, request, history_messages)
        context.generation_metadata = metadata
        risk_level = self._single_risk_level(context, draft.risk_level)
        response = self._build_single_response(context, draft, risk_level)
        _save_assistant_message(self.db, conversation, response)
        return response

    def run_fleet(
        self,
        request: MultiDeviceRiskRequest,
    ) -> MultiDeviceRiskResponse:
        plan = self.planner.plan_fleet(request)
        context = self._start_context(
            mode="multi_device",
            query=request.query,
            device_code=None,
            planned_tools=plan.tool_names,
            reason=plan.reason,
        )

        list_record = self.engine.execute("list_devices", {})
        context.tool_records.append(list_record)
        devices = list_record.result.get("devices") if list_record.status == "success" else []
        if not isinstance(devices, list):
            devices = []
        context.warnings.extend(
            warning
            for warning in _data_quality_warnings(
                request.query,
                [str(device.get("device_code")) for device in devices if isinstance(device, dict)],
            )
            if warning not in context.warnings
        )

        device_risks: list[DeviceRiskItem] = []
        for device in devices:
            device_code = str(device.get("device_code") or "")
            if not device_code:
                continue
            status_result, alarms_result, knowledge_results = self._collect_device_evidence(
                context,
                request.query,
                device_code,
                top_k=request.knowledge_top_k,
                include_knowledge=request.include_knowledge,
            )
            if status_result is not None and status_result.ok and status_result.device is not None:
                device_risks.append(
                    self._build_device_risk_item(
                        status_result,
                        alarms_result,
                        knowledge_results,
                    )
                )

        device_risks.sort(key=lambda item: item.risk_score, reverse=True)
        draft, metadata = self._generate_fleet_draft(context, request, device_risks)
        context.generation_metadata = metadata
        warnings = _dedupe([*context.warnings, *draft.warnings])
        response = MultiDeviceRiskResponse(
            query=request.query,
            summary=draft.summary,
            overall_risk_level=_max_risk_level(
                [item.risk_level for item in device_risks] + [draft.overall_risk_level]
            ),
            device_risks=device_risks,
            key_findings=draft.key_findings,
            recommended_actions=draft.recommended_actions,
            sources=_knowledge_sources(context),
            tools_used=_dedupe(
                [
                    *self._successful_tools(context),
                    *(
                        ["llm_risk_report"]
                        if metadata.mode in {"production", "mock"}
                        else []
                    ),
                ]
            ),
            warnings=warnings,
            confidence=self._confidence(context, metadata.mode == "production"),
            disclaimer=DISCLAIMER,
            created_at=now_utc(),
        )
        return response

    def _start_context(
        self,
        *,
        mode: str,
        query: str,
        device_code: str | None,
        planned_tools: list[str],
        reason: str,
    ) -> DiagnosisOrchestratorContext:
        trace_mode = "multi_device_risk" if mode == "multi_device" else mode
        trace = agent_trace.start_agent_trace(
            mode=trace_mode,
            query=query,
            device_code=device_code,
        )
        agent_trace.record_router_selection(planned_tools)
        diagnosis_trace = DiagnosisTrace(
            mode="multi_device" if mode == "multi_device" else "runtime",
            device_id=device_code,
        )
        diagnosis_trace.add_step(
            "IntentPlanner",
            "success",
            {"tools": planned_tools, "reason": reason},
        )
        if isinstance(trace, dict):
            trace["diagnosis_trace_id"] = diagnosis_trace.id
            trace["orchestrator"] = "DiagnosisOrchestrator"
        return DiagnosisOrchestratorContext(
            mode="multi_device" if mode == "multi_device" else "runtime",
            query=query,
            device_code=device_code,
            planned_tools=planned_tools,
            trace=diagnosis_trace,
        )

    def _load_device_context(self, device_code: str) -> DeviceContext | None:
        if not all(hasattr(self.db, name) for name in ("scalar", "scalars")):
            return None
        try:
            device_context = build_device_context(self.db, device_code)
        except Exception:
            logger.exception("Device context build failed. device_code=%s", device_code)
            return None
        if not device_context.exists:
            return None
        agent_trace.record_device_context(device_context.compact())
        return device_context

    def _collect_device_context_evidence(
        self,
        context: DiagnosisOrchestratorContext,
    ) -> None:
        device_context = context.device_context
        if device_context is None or not device_context.exists:
            return

        compact = device_context.compact()
        context.evidence.history_cases.append(
            EvidenceItem(
                kind="history",
                source="device_context",
                timestamp=now_utc(),
                confidence=0.9,
                content={
                    "health_summary": compact.get("health_summary"),
                    "diagnosis_history": compact.get("diagnosis_history"),
                    "risk_trend": compact.get("risk_trend"),
                    "maintenance_memory": compact.get("maintenance_memory"),
                    "similar_cases": compact.get("similar_cases"),
                },
            )
        )
        context.trace.add_step(
            "DeviceContext",
            "success",
            {
                "diagnosis_count": (
                    device_context.health_summary.diagnosis_count
                    if device_context.health_summary
                    else 0
                ),
                "maintenance_record_count": (
                    device_context.health_summary.maintenance_record_count
                    if device_context.health_summary
                    else 0
                ),
                "similar_case_count": len(device_context.similar_cases),
            },
        )

    def _execute_single_plan(
        self,
        context: DiagnosisOrchestratorContext,
        request: AgentDiagnoseRequest,
        plan: ToolPlan,
        knowledge_query_basis: str,
    ) -> None:
        status_result: DeviceStatusToolResult | None = None
        alarms_result: DeviceAlarmsToolResult | None = None
        if "get_device_status" in plan.tool_names and plan.device_code:
            record = self.engine.execute(
                "get_device_status",
                DeviceStatusToolInput(device_code=plan.device_code, alarm_limit=20).model_dump(),
                trace_context={"device_code": plan.device_code},
            )
            context.tool_records.append(record)
            status_result = _validate_tool_result(DeviceStatusToolResult, record.result)
            self._collect_status_evidence(context, status_result)

        if "get_device_alarms" in plan.tool_names:
            record = self.engine.execute(
                "get_device_alarms",
                {
                    "device_code": plan.device_code,
                    "limit": 20,
                    "unresolved_only": True,
                },
                trace_context={"device_code": plan.device_code},
            )
            context.tool_records.append(record)
            alarms_result = _validate_tool_result(DeviceAlarmsToolResult, record.result)
            self._collect_alarm_evidence(context, alarms_result)

        should_search_knowledge = "search_knowledge" in plan.tool_names
        if (
            not should_search_knowledge
            and request.include_knowledge
            and _has_unresolved_alarm_result(alarms_result)
        ):
            should_search_knowledge = True

        if should_search_knowledge:
            search_queries = self._single_knowledge_queries(
                knowledge_query_basis,
                status_result,
                alarms_result,
            )
            search_queries = build_context_aware_queries(
                user_query=knowledge_query_basis,
                device_context=context.device_context,
                base_queries=search_queries,
            )
            if not search_queries:
                if "search_knowledge" in plan.tool_names:
                    context.add_warning("User concern does not match current device alarms or abnormal parameters.")
            for query, alarm_code in search_queries:
                record = self.engine.search_knowledge(
                    query,
                    request.knowledge_top_k,
                    trace_context={
                        "device_code": plan.device_code,
                        "alarm_code": alarm_code,
                        "query": _display_knowledge_query(query),
                    },
                )
                context.tool_records.append(record)
                knowledge_result = _validate_tool_result(KnowledgeSearchToolResult, record.result)
                self._collect_knowledge_evidence(context, knowledge_result)

    def _collect_device_evidence(
        self,
        context: DiagnosisOrchestratorContext,
        user_query: str,
        device_code: str,
        *,
        top_k: int,
        include_knowledge: bool,
    ) -> tuple[
        DeviceStatusToolResult | None,
        DeviceAlarmsToolResult | None,
        list[KnowledgeSearchToolResult],
    ]:
        device_context = self._load_device_context(device_code)
        if device_context is not None:
            context.device_context = device_context
            self._collect_device_context_evidence(context)

        status_record = self.engine.execute(
            "get_device_status",
            {"device_code": device_code, "alarm_limit": 20},
            trace_context={"device_code": device_code},
        )
        context.tool_records.append(status_record)
        status_result = _validate_tool_result(DeviceStatusToolResult, status_record.result)
        self._collect_status_evidence(context, status_result)

        alarms_record = self.engine.execute(
            "get_device_alarms",
            {"device_code": device_code, "limit": 20, "unresolved_only": True},
            trace_context={"device_code": device_code},
        )
        context.tool_records.append(alarms_record)
        alarms_result = _validate_tool_result(DeviceAlarmsToolResult, alarms_record.result)
        self._collect_alarm_evidence(context, alarms_result)

        knowledge_results: list[KnowledgeSearchToolResult] = []
        if include_knowledge:
            base_queries = self._fleet_knowledge_queries(user_query, alarms_result)
            for query, alarm_code in build_context_aware_queries(
                user_query=user_query,
                device_context=device_context,
                base_queries=base_queries,
            ):
                record = self.engine.search_knowledge(
                    query,
                    top_k,
                    trace_context={
                        "device_code": device_code,
                        "alarm_code": alarm_code,
                        "query": _display_knowledge_query(query),
                    },
                )
                context.tool_records.append(record)
                knowledge_result = _validate_tool_result(KnowledgeSearchToolResult, record.result)
                knowledge_results.append(knowledge_result)
                self._collect_knowledge_evidence(context, knowledge_result)
                if knowledge_result is not None and not knowledge_result.results:
                    context.add_warning(f"未找到匹配的维修知识：{device_code} {alarm_code}")

        return status_result, alarms_result, knowledge_results

    def _collect_status_evidence(
        self,
        context: DiagnosisOrchestratorContext,
        result: DeviceStatusToolResult | None,
    ) -> None:
        if result is None:
            context.add_warning("Device status tool result could not be used.")
            return
        if not result.ok and result.error_code:
            context.add_warning("Device status tool unavailable.")
            context.add_warning("Device status query failed.")
        context.warnings.extend(warning for warning in result.warnings if warning not in context.warnings)
        if result.device is not None:
            context.evidence.device_facts.append(
                EvidenceItem(
                    kind="device",
                    source="get_device_status",
                    timestamp=now_utc(),
                    confidence=1.0,
                    content=result.device.model_dump(mode="json"),
                )
            )
        if result.latest_runtime_data is not None:
            runtime_payload = result.latest_runtime_data.model_dump(mode="json")
            context.evidence.parameter_observations.append(
                EvidenceItem(
                    kind="runtime",
                    source="get_device_status",
                    timestamp=now_utc(),
                    confidence=0.95,
                    content=runtime_payload,
                )
            )
        for alarm in result.recent_alarms:
            context.evidence.alarm_facts.append(
                EvidenceItem(
                    kind="alarm",
                    source="get_device_status",
                    timestamp=now_utc(),
                    confidence=0.95,
                    content=alarm.model_dump(mode="json"),
                )
            )

    def _collect_alarm_evidence(
        self,
        context: DiagnosisOrchestratorContext,
        result: DeviceAlarmsToolResult | None,
    ) -> None:
        if result is None:
            context.add_warning("Alarm tool result could not be used.")
            return
        if not result.ok and result.error_code:
            context.add_warning("Device alarm query failed.")
        context.warnings.extend(warning for warning in result.warnings if warning not in context.warnings)
        for alarm in result.alarms:
            context.evidence.alarm_facts.append(
                EvidenceItem(
                    kind="alarm",
                    source="get_device_alarms",
                    timestamp=now_utc(),
                    confidence=1.0,
                    content=alarm.model_dump(mode="json"),
                )
            )

    def _collect_knowledge_evidence(
        self,
        context: DiagnosisOrchestratorContext,
        result: KnowledgeSearchToolResult | None,
    ) -> None:
        if result is None:
            context.add_warning("Knowledge search tool result could not be used.")
            return
        if not result.ok and result.error_code:
            context.add_warning("Knowledge search tool unavailable.")
        context.warnings.extend(warning for warning in result.warnings if warning not in context.warnings)
        for item in result.results:
            context.evidence.knowledge_evidence.append(
                EvidenceItem(
                    kind="knowledge",
                    source=item.source,
                    timestamp=now_utc(),
                    confidence=max(0.0, min(1.0, 1.0 - item.distance)),
                    content=item.model_dump(mode="json"),
                )
            )

    def _generate_single_draft(
        self,
        context: DiagnosisOrchestratorContext,
        request: AgentDiagnoseRequest,
        history_messages: list[Message],
    ) -> tuple[AgentDiagnosisDraft, GenerationMetadata]:
        if not context.evidence.has_evidence():
            return _single_fallback_draft("当前缺少可用于诊断的设备、报警或知识库证据。"), _metadata(
                self.llm_provider,
                "fallback",
            )
        messages = _single_llm_messages(context, request, history_messages)
        try:
            draft = self.llm_provider.complete_structured(messages, AgentDiagnosisDraft)
            metadata = _metadata(self.llm_provider, "production")
            agent_trace.record_llm_final_status(
                status="mock" if metadata.mode == "mock" else "success",
                metadata=metadata.model_dump(mode="json"),
            )
            context.trace.add_step("LLMReasoning", "success", {"mode": metadata.mode})
            return draft, metadata
        except Exception:
            logger.exception("DiagnosisOrchestrator single LLM generation failed.")
            fallback_metadata = _metadata(self.llm_provider, "fallback")
            agent_trace.record_llm_final_status(
                status="fallback",
                fallback_reason="llm_failed",
                metadata=fallback_metadata.model_dump(mode="json"),
            )
            context.trace.add_step("LLMReasoning", "fallback", {"reason": "llm_failed"})
            return _single_fallback_draft(_llm_unavailable_summary(context)), _metadata(
                self.llm_provider,
                "fallback",
            )

    def _generate_fleet_draft(
        self,
        context: DiagnosisOrchestratorContext,
        request: MultiDeviceRiskRequest,
        device_risks: list[DeviceRiskItem],
    ) -> tuple[MultiDeviceRiskDraft, GenerationMetadata]:
        messages = _fleet_llm_messages(context, request, device_risks)
        try:
            draft = self.llm_provider.complete_structured(messages, MultiDeviceRiskDraft)
            metadata = _metadata(self.llm_provider, "production")
            agent_trace.record_llm_final_status(
                status="mock" if metadata.mode == "mock" else "success",
                metadata=metadata.model_dump(mode="json"),
            )
            context.trace.add_step("LLMReasoning", "success", {"mode": metadata.mode})
            return draft, metadata
        except Exception:
            logger.exception("DiagnosisOrchestrator fleet LLM generation failed.")
            fallback_metadata = _metadata(self.llm_provider, "fallback")
            agent_trace.record_llm_final_status(
                status="fallback",
                fallback_reason="llm_failed",
                metadata=fallback_metadata.model_dump(mode="json"),
            )
            context.trace.add_step("LLMReasoning", "fallback", {"reason": "llm_failed"})
            return _fleet_fallback_draft(device_risks), _metadata(self.llm_provider, "fallback")

    def _build_single_response(
        self,
        context: DiagnosisOrchestratorContext,
        draft: AgentDiagnosisDraft,
        risk_level: RiskLevel,
    ) -> AgentDiagnoseResponse:
        status_result = self._latest_status_result(context)
        alarms_result = self._latest_alarms_result(context)
        recent_alarms = status_result.recent_alarms if status_result is not None and status_result.ok else []
        if alarms_result is not None and alarms_result.ok and not recent_alarms:
            recent_alarms = _tool_alarm_records_from_alarm_result(status_result, alarms_result)
        warnings = _dedupe([*context.warnings, *draft.warnings])
        return AgentDiagnoseResponse(
            problem_summary=draft.problem_summary,
            device=status_result.device if status_result is not None and status_result.ok else None,
            device_status=(
                status_result.latest_runtime_data
                if status_result is not None and status_result.ok
                else None
            ),
            recent_alarms=recent_alarms,
            risk_level=risk_level,
            possible_causes=draft.possible_causes,
            recommended_actions=draft.recommended_actions,
            sources=context.evidence.sources(),
            tools_used=self._successful_tools(context),
            warnings=warnings,
            disclaimer=DISCLAIMER,
        )

    def _single_risk_level(
        self,
        context: DiagnosisOrchestratorContext,
        proposed_level: str,
    ) -> RiskLevel:
        deterministic = "unknown"
        status_result = self._latest_status_result(context)
        alarms = status_result.recent_alarms if status_result is not None and status_result.ok else []
        highest_alarm = _max_alarm_level([alarm.alarm_level for alarm in alarms])
        if highest_alarm is not None:
            deterministic = highest_alarm
        runtime = status_result.latest_runtime_data if status_result is not None and status_result.ok else None
        device_type = status_result.device.device_type if status_result and status_result.device else None
        observations = evaluate_runtime_parameters(
            device_type,
            runtime.model_dump(mode="json") if runtime is not None else {},
        )
        if any(observation.status == "critical" for observation in observations):
            deterministic = _max_risk_level([deterministic, "high"])
        elif any(observation.status == "warning" for observation in observations):
            deterministic = _max_risk_level([deterministic, "medium"])
        return _max_risk_level([proposed_level, deterministic])

    def _build_device_risk_item(
        self,
        status_result: DeviceStatusToolResult,
        alarms_result: DeviceAlarmsToolResult | None,
        knowledge_results: list[KnowledgeSearchToolResult],
    ) -> DeviceRiskItem:
        assert status_result.device is not None
        alarms = list(status_result.recent_alarms)
        if alarms_result is not None and alarms_result.ok and not alarms:
            alarms = _tool_alarm_records_from_alarm_result(status_result, alarms_result)
        runtime = status_result.latest_runtime_data
        observations = evaluate_runtime_parameters(
            status_result.device.device_type,
            runtime.model_dump(mode="json") if runtime is not None else {},
        )
        exceeded = any(observation.status == "critical" for observation in observations)
        warning = any(observation.status == "warning" for observation in observations)
        risk_level = _classify_device_risk(alarms, exceeded, warning)
        knowledge_sources = _dedupe(
            [
                item.source
                for knowledge_result in knowledge_results
                if knowledge_result is not None and knowledge_result.ok
                for item in knowledge_result.results
            ]
        )
        reasons = _device_risk_reasons(alarms, observations, status_result.device.is_online, knowledge_sources)
        return DeviceRiskItem(
            device=status_result.device,
            latest_runtime_data=runtime,
            unresolved_alarms=alarms,
            risk_level=risk_level,
            risk_score=_risk_score(risk_level, alarms, observations),
            reasons=reasons,
            knowledge_sources=knowledge_sources,
            recommended_actions=_device_actions(risk_level, alarms, bool(knowledge_sources)),
        )

    def _single_knowledge_queries(
        self,
        user_query: str,
        status_result: DeviceStatusToolResult | None,
        alarms_result: DeviceAlarmsToolResult | None,
    ) -> list[tuple[str, str | None]]:
        concerns = _query_concerns(user_query)
        alarm_terms = _alarm_terms(status_result, alarms_result)
        if concerns:
            alarm_terms = [
                alarm
                for alarm in alarm_terms
                if ALARM_PARAMETER_HINTS.get(alarm["code"], set()) & concerns
            ]
            if not alarm_terms:
                alarm_terms = _inferred_alarm_terms_from_abnormal_concerns(
                    status_result,
                    concerns,
                )
            if not alarm_terms and (
                status_result is None or not status_result.ok or _extract_fault_codes(user_query)
            ):
                return [(user_query, None)]
            if not alarm_terms and not _concern_parameter_is_abnormal(status_result, concerns):
                return []
        if alarm_terms:
            return [
                (
                    _join_query_parts(
                        [
                            alarm["code"],
                            alarm["name"],
                            user_query,
                            _device_type(status_result),
                            "maintenance handling steps",
                        ]
                    ),
                    alarm["code"],
                )
                for alarm in alarm_terms
            ]
        return [(user_query, None)]

    def _fleet_knowledge_queries(
        self,
        user_query: str,
        alarms_result: DeviceAlarmsToolResult | None,
    ) -> list[tuple[str, str | None]]:
        if alarms_result is None or not alarms_result.ok:
            return []
        return [
            (
                _join_query_parts(
                    [
                        alarm.alarm_code,
                        alarm.alarm_name,
                        "handling steps",
                    ]
                ),
                alarm.alarm_code,
            )
            for alarm in sorted(alarms_result.alarms, key=lambda item: item.alarm_code)
            if alarm.status != "resolved"
        ]

    def _latest_status_result(
        self,
        context: DiagnosisOrchestratorContext,
    ) -> DeviceStatusToolResult | None:
        for record in reversed(context.tool_records):
            if record.tool_name == "get_device_status" and record.status == "success":
                return _validate_tool_result(DeviceStatusToolResult, record.result)
        return None

    def _latest_alarms_result(
        self,
        context: DiagnosisOrchestratorContext,
    ) -> DeviceAlarmsToolResult | None:
        for record in reversed(context.tool_records):
            if record.tool_name == "get_device_alarms" and record.status == "success":
                return _validate_tool_result(DeviceAlarmsToolResult, record.result)
        return None

    def _successful_tools(self, context: DiagnosisOrchestratorContext) -> list[str]:
        tools: list[str] = []
        for record in context.tool_records:
            if record.status == "success" and record.tool_name not in tools:
                tools.append(record.tool_name)
        if context.generation_metadata.mode == "production":
            tools.append("llm_reasoning")
        return tools

    def _confidence(self, context: DiagnosisOrchestratorContext, llm_success: bool) -> int:
        score = 20
        if context.evidence.device_facts:
            score += 20
        if context.evidence.parameter_observations:
            score += 20
        if context.evidence.alarm_facts:
            score += 15
        if context.evidence.knowledge_evidence:
            score += 15
        if llm_success:
            score += 5
        return max(20, min(90, score))


def _has_unresolved_alarm_result(result: DeviceAlarmsToolResult | None) -> bool:
    if result is None or not result.ok:
        return False
    return any(alarm.status != "resolved" for alarm in result.alarms)


def _single_llm_messages(
    context: DiagnosisOrchestratorContext,
    request: AgentDiagnoseRequest,
    history_messages: list[Message],
) -> list[LLMMessage]:
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are an enterprise industrial equipment diagnosis assistant. "
                "Use only the provided DiagnosisEvidenceBundle. Explain possible causes "
                "and maintenance actions. Do not decide device facts, alarms, risk level, "
                "or citations. Output valid JSON fields: problem_summary, risk_level, "
                "possible_causes, recommended_actions, warnings."
            ),
        ),
    ]
    for message in history_messages[-10:]:
        if message.role in {"user", "assistant"}:
            messages.append(LLMMessage(role=message.role, content=message.content))
    messages.append(
        LLMMessage(
            role="user",
            content=json.dumps(
                {
                    "query": request.query,
                    "device_code": request.device_code,
                    "device_context": (
                        context.device_context.compact()
                        if context.device_context is not None
                        else None
                    ),
                    "evidence_bundle": context.evidence.model_dump(mode="json"),
                    "planned_tools": context.planned_tools,
                },
                ensure_ascii=False,
            ),
        ),
    )
    return messages


def _fleet_llm_messages(
    context: DiagnosisOrchestratorContext,
    request: MultiDeviceRiskRequest,
    device_risks: list[DeviceRiskItem],
) -> list[LLMMessage]:
    return [
        LLMMessage(
            role="system",
            content=(
                "You are an enterprise fleet risk analysis assistant. Use only the "
                "provided deterministic device risks and DiagnosisEvidenceBundle. "
                "Do not invent devices, alarms, metrics, risk levels, or citations. "
                "Output valid JSON fields: summary, overall_risk_level, key_findings, "
                "recommended_actions, warnings."
            ),
        ),
        LLMMessage(
            role="user",
            content=json.dumps(
                {
                    "query": request.query,
                    "device_risks": [item.model_dump(mode="json") for item in device_risks],
                    "device_context": (
                        context.device_context.compact()
                        if context.device_context is not None
                        else None
                    ),
                    "knowledge_evidence": _legacy_knowledge_evidence(context),
                    "evidence_bundle": context.evidence.model_dump(mode="json"),
                    "planned_tools": context.planned_tools,
                },
                ensure_ascii=False,
            ),
        ),
    ]


def _validate_tool_result(model: type[Any], payload: dict[str, Any]) -> Any:
    try:
        return model.model_validate(payload)
    except Exception:
        logger.exception("Tool result validation failed. model=%s", model.__name__)
        return None


def _metadata(provider: LLMProvider, mode: str) -> GenerationMetadata:
    provider_name = provider.__class__.__name__.lower()
    if "mock" in provider_name:
        provider_value = "mock"
        mode = "mock" if mode == "production" else mode
    elif "ollama" in provider_name:
        provider_value = "ollama"
    elif "openai" in provider_name:
        provider_value = "openai_compatible"
    else:
        provider_value = "unknown"
    call_metadata = getattr(provider, "last_call_metadata", None)
    metadata_payload = {
        "provider": provider_value,
        "mode": mode,
        "model": getattr(provider, "model", None),
        "fallback_occurred": mode == "fallback",
    }
    if isinstance(call_metadata, dict) and mode != "mock":
        metadata_payload.update(
            {
                "request_id": call_metadata.get("request_id"),
                "response_id": call_metadata.get("response_id"),
                "latency_ms": call_metadata.get("latency_ms"),
                "prompt_tokens": call_metadata.get("prompt_tokens"),
                "completion_tokens": call_metadata.get("completion_tokens"),
                "total_tokens": call_metadata.get("total_tokens"),
                "fallback_occurred": bool(call_metadata.get("fallback_occurred", mode == "fallback")),
            }
        )
    return GenerationMetadata(**metadata_payload)  # type: ignore[arg-type]


def _single_fallback_draft(summary: str) -> AgentDiagnosisDraft:
    return AgentDiagnosisDraft(
        problem_summary=summary,
        risk_level="unknown",
        possible_causes=[],
        recommended_actions=[
            "请提供设备编号。",
            "请提供报警码或故障现象。",
            "请结合设备状态、报警记录和现场情况进行复核。",
            "如存在安全风险，请先降低负载或停机检查。",
        ],
        warnings=[
            LLM_UNAVAILABLE_WARNING,
            "智能推理服务暂时不可用，已生成规则化诊断结果。",
        ],
    )


def _fleet_fallback_draft(device_risks: list[DeviceRiskItem]) -> MultiDeviceRiskDraft:
    risky = [item for item in device_risks if item.risk_level not in {"normal", "unknown"}]
    return MultiDeviceRiskDraft(
        summary=f"本次共分析 {len(device_risks)} 台设备，其中 {len(risky)} 台存在风险信号。",
        overall_risk_level=_max_risk_level([item.risk_level for item in device_risks]),
        key_findings=[
            f"{item.device.device_code}: {', '.join(item.reasons[:2]) or '运行参数正常'}"
            for item in device_risks[:8]
        ],
        recommended_actions=[
            "优先处理高风险设备的未关闭报警。",
            "安排中风险设备巡检，确认运行参数和异常原因。",
            "对正常设备保持日常监控并记录趋势。",
        ],
        warnings=[
            "智能推理服务暂时不可用，已生成确定性风险汇总。",
            "智能推理服务暂时不可用，已生成规则化多设备风险报告。",
        ],
    )


def _history_augmented_query(query: str, history_messages: list[Message]) -> str:
    history = [
        message.content.strip()
        for message in history_messages
        if message.role == "user" and message.content.strip()
    ]
    if not history:
        return query
    return " ".join([*history[-3:], query])


def _history_fault_codes(history_messages: list[Message]) -> list[str]:
    codes: list[str] = []
    for message in history_messages:
        if message.role != "user":
            continue
        for match in re.finditer(r"\b[A-Z]\d{3,}\b", message.content, re.IGNORECASE):
            code = match.group(0).upper()
            if code not in codes:
                codes.append(code)
    return codes


def _data_quality_warnings(query: str, device_codes: list[str]) -> list[str]:
    requested_codes = {
        match.group(0).upper() for match in re.finditer(r"\bDEV-\d+\b", query, re.IGNORECASE)
    }
    missing_codes = sorted(requested_codes - set(device_codes))
    return [
        f"Data quality warning: requested device does not exist and is excluded from risk ranking: {device_code}"
        for device_code in missing_codes
    ]


def _legacy_knowledge_evidence(
    context: DiagnosisOrchestratorContext,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for record in context.tool_records:
        if record.tool_name != "search_knowledge":
            continue
        trace_context = record.result.get("_trace")
        if not isinstance(trace_context, dict):
            trace_context = {}
        results = record.result.get("results")
        evidence.append(
            {
                "device_code": trace_context.get("device_code"),
                "alarm_code": trace_context.get("alarm_code"),
                "results": results if isinstance(results, list) else [],
                "warnings": (
                    record.result.get("warnings")
                    if isinstance(record.result.get("warnings"), list)
                    else []
                ),
            }
        )
    return evidence


def _deterministic_single_summary(context: DiagnosisOrchestratorContext) -> str:
    status_result = None
    for record in reversed(context.tool_records):
        if record.tool_name == "get_device_status":
            status_result = _validate_tool_result(DeviceStatusToolResult, record.result)
            break
    if status_result is not None and status_result.device is not None:
        alarm_codes = [
            alarm.alarm_code
            for alarm in status_result.recent_alarms
            if not alarm.is_resolved
        ]
        if alarm_codes:
            return f"{status_result.device.device_code} 当前存在 {', '.join(alarm_codes)} 报警，需要结合现场检查确认原因。"
        return f"{status_result.device.device_code} 当前未发现未处理报警，请继续核对用户描述和现场状态。"
    return "当前缺少可用于诊断的设备状态证据。"


def _llm_unavailable_summary(context: DiagnosisOrchestratorContext) -> str:
    deterministic_summary = _deterministic_single_summary(context)
    return f"当前 AI 诊断服务暂时不可用，以下结果基于设备数据和知识库信息生成。{deterministic_summary}"


def _extract_fault_codes(query: str) -> list[str]:
    result: list[str] = []
    for match in re.finditer(r"\b[A-Z]\d{3,}\b", query, re.IGNORECASE):
        code = match.group(0).upper()
        if code not in result:
            result.append(code)
    return result


def _tool_alarm_records_from_alarm_result(
    status_result: DeviceStatusToolResult | None,
    alarms_result: DeviceAlarmsToolResult,
) -> list[ToolAlarmRecord]:
    if status_result is None or status_result.device is None:
        return []
    return [
        ToolAlarmRecord(
            id=index + 1,
            device_id=status_result.device.id,
            alarm_code=alarm.alarm_code,
            alarm_level=alarm.level,
            message=alarm.alarm_name,
            is_resolved=alarm.status == "resolved",
            occurred_at=alarm.created_at,
            resolved_at=None,
            created_at=alarm.created_at,
        )
        for index, alarm in enumerate(alarms_result.alarms)
    ]


def _alarm_terms(
    status_result: DeviceStatusToolResult | None,
    alarms_result: DeviceAlarmsToolResult | None,
) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    if alarms_result is not None and alarms_result.ok:
        for alarm in alarms_result.alarms:
            if alarm.status == "resolved":
                continue
            terms.append(
                {
                    "code": alarm.alarm_code,
                    "name": alarm.alarm_name or alarm_display_name(alarm.alarm_code),
                }
            )
    if status_result is not None and status_result.ok:
        for alarm in status_result.recent_alarms:
            if alarm.is_resolved:
                continue
            if not any(term["code"] == alarm.alarm_code for term in terms):
                terms.append(
                    {
                        "code": alarm.alarm_code,
                        "name": alarm.message or alarm_display_name(alarm.alarm_code),
                    }
                )
    return terms


def _query_concerns(query: str) -> set[str]:
    return {
        parameter
        for parameter, keywords in PARAMETER_CONCERN_KEYWORDS.items()
        if any(keyword in query for keyword in keywords)
    }


def _concern_parameter_is_abnormal(
    status_result: DeviceStatusToolResult | None,
    concerns: set[str],
) -> bool:
    if status_result is None or status_result.latest_runtime_data is None:
        return False
    runtime = status_result.latest_runtime_data.model_dump(mode="json")
    observations = evaluate_runtime_parameters(
        status_result.device.device_type if status_result.device is not None else None,
        runtime,
    )
    return any(
        observation.parameter in concerns and observation.status in {"warning", "critical"}
        for observation in observations
    )


def _inferred_alarm_terms_from_abnormal_concerns(
    status_result: DeviceStatusToolResult | None,
    concerns: set[str],
) -> list[dict[str, str]]:
    if status_result is None or status_result.latest_runtime_data is None:
        return []
    runtime = status_result.latest_runtime_data.model_dump(mode="json")
    observations = evaluate_runtime_parameters(
        status_result.device.device_type if status_result.device is not None else None,
        runtime,
    )
    terms: list[dict[str, str]] = []
    for observation in observations:
        if observation.parameter not in concerns:
            continue
        if observation.status not in {"warning", "critical"}:
            continue
        alarm_code = PARAMETER_FAULT_HINTS.get(observation.parameter)
        if alarm_code is None:
            continue
        if not any(term["code"] == alarm_code for term in terms):
            terms.append(
                {
                    "code": alarm_code,
                    "name": alarm_display_name(alarm_code),
                }
            )
    return terms


def _device_type(status_result: DeviceStatusToolResult | None) -> str | None:
    if status_result is not None and status_result.device is not None:
        return status_result.device.device_type
    return None


def _join_query_parts(parts: list[str | None]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = " ".join(str(part or "").split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return " ".join(result)


def _display_knowledge_query(query: str) -> str:
    markers = [" maintenance handling steps", " handling steps"]
    for marker in markers:
        index = query.find(marker)
        if index >= 0:
            return f"{query[:index]}{marker}".strip()
    return query


def _classify_device_risk(
    alarms: list[ToolAlarmRecord],
    parameter_exceeded: bool,
    parameter_warning: bool,
) -> RiskLevel:
    alarm_level = _max_alarm_level([alarm.alarm_level for alarm in alarms])
    if alarm_level in {"critical", "high"} or parameter_exceeded:
        return "high"
    if alarm_level in {"medium", "low"} or alarms or parameter_warning:
        return "medium"
    return "normal"


def _risk_score(
    risk_level: str,
    alarms: list[ToolAlarmRecord],
    observations: list[Any],
) -> int:
    base = {
        "normal": 10,
        "low": 30,
        "medium": 58,
        "high": 82,
        "critical": 95,
        "unknown": 0,
    }.get(risk_level, 0)
    base += min(8, len(alarms) * 2)
    base += sum(5 for observation in observations if observation.status == "critical")
    base += sum(2 for observation in observations if observation.status == "warning")
    return min(100, base)


def _device_risk_reasons(
    alarms: list[ToolAlarmRecord],
    observations: list[Any],
    is_online: bool,
    knowledge_sources: list[str],
) -> list[str]:
    reasons: list[str] = []
    if not is_online:
        reasons.append("设备离线")
    if alarms:
        reasons.append(f"{len(alarms)} 条未处理报警")
    for observation in observations:
        if observation.status in {"warning", "critical"}:
            reasons.append(observation.explanation)
    if alarms and not knowledge_sources:
        reasons.append("未找到匹配的维修知识依据")
    if not reasons:
        reasons.append("无报警且运行参数正常")
    return _dedupe(reasons)


def _device_actions(
    risk_level: str,
    alarms: list[ToolAlarmRecord],
    has_knowledge: bool,
) -> list[str]:
    actions: list[str] = []
    if risk_level == "high":
        actions.append("复核高风险设备报警，必要时降低负载或安排停机检查。")
    if alarms:
        actions.append("检查未处理报警记录，并确认现场设备当前状态。")
    if has_knowledge:
        actions.append("按照引用的维修资料逐项验证。")
    if not actions:
        actions.append("继续保持日常监控。")
    return actions


def _max_alarm_level(levels: list[str]) -> str | None:
    valid = [level.lower() for level in levels if level and level.lower() in ALARM_LEVEL_ORDER]
    if not valid:
        return None
    return max(valid, key=lambda level: ALARM_LEVEL_ORDER[level])


def _max_risk_level(levels: list[str]) -> RiskLevel:
    valid = [level for level in levels if level in RISK_ORDER]
    if not valid:
        return "unknown"
    return max(valid, key=lambda level: RISK_ORDER[level])  # type: ignore[return-value]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _knowledge_sources(context: DiagnosisOrchestratorContext) -> list[str]:
    """Return knowledge sources even if evidence collection missed a tool result."""

    sources = list(context.evidence.sources())
    for record in context.tool_records:
        if record.tool_name != "search_knowledge" or record.status != "success":
            continue
        raw_results = record.result.get("results") if isinstance(record.result, dict) else None
        if not isinstance(raw_results, list):
            continue
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            source = item.get("source") or item.get("filename")
            if isinstance(source, str) and source:
                sources.append(source)
    return _dedupe(sources)


def _get_request_conversation(
    db: Session,
    request: AgentDiagnoseRequest,
) -> Conversation | None:
    if request.conversation_id is None:
        return None
    return conversation_service.get_conversation(db, request.conversation_id)


def _get_request_history(
    db: Session,
    request: AgentDiagnoseRequest,
    conversation: Conversation | None,
) -> list[Message]:
    if request.conversation_id is None or conversation is None:
        return []
    return conversation_service.get_recent_messages(
        db,
        request.conversation_id,
        limit=10,
    )


def _save_user_message(
    db: Session,
    conversation: Conversation | None,
    request: AgentDiagnoseRequest,
) -> None:
    if conversation is None:
        return
    conversation_service.add_message(
        db,
        conversation,
        role="user",
        content=request.query,
    )


def _save_assistant_message(
    db: Session,
    conversation: Conversation | None,
    response: AgentDiagnoseResponse,
) -> None:
    if conversation is None:
        return
    conversation_service.add_message(
        db,
        conversation,
        role="assistant",
        content=response.model_dump_json(),
    )
