import logging
import re

from sqlalchemy.orm import Session

from app.agent.prompts import build_diagnosis_messages
from app.agent.tools import run_get_device_status_tool, run_search_knowledge_tool
from app.conversation import service as conversation_service
from app.conversation.models import Conversation, Message
from app.llm.base import (
    LLMProvider,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.schemas.agent import (
    AgentDiagnoseResponse,
    AgentDiagnoseRequest,
    AgentDiagnosisDraft,
    AgentToolPlan,
    AgentWorkflowContext,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ParsedAgentQuery,
    ToolAlarmRecord,
    enforce_minimum_risk_level,
)


DEVICE_CODE_PATTERN = re.compile(r"\bDEV-\d+\b", re.IGNORECASE)
FAULT_CODE_PATTERN = re.compile(r"\b[A-Z]\d{3,}\b", re.IGNORECASE)
FAULT_SYMPTOM_KEYWORDS = [
    "\u62a5\u8b66",
    "\u6545\u969c",
    "\u5f02\u5e38",
    "\u6e29\u5ea6\u8fc7\u9ad8",
    "\u5347\u6e29",
    "\u8fc7\u70ed",
    "\u7535\u538b",
    "\u632f\u52a8",
    "\u901a\u4fe1",
    "\u4f20\u611f\u5668",
    "\u98ce\u6247",
    "\u600e\u4e48\u5904\u7406",
    "\u4ec0\u4e48\u539f\u56e0",
]
STATUS_KEYWORDS = [
    "\u72b6\u6001",
    "\u5f53\u524d",
    "\u5728\u7ebf",
    "\u8fd0\u884c",
]
INFO_KEYWORDS = [
    "\u4ecb\u7ecd",
    "\u4fe1\u606f",
    "\u8be6\u60c5",
    "\u57fa\u672c",
]
RISK_ORDER = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
QUERY_PARAMETER_KEYWORDS = {
    "temperature": ["温度", "过热", "升温", "高温"],
    "vibration": ["振动", "震动"],
    "current": ["电流"],
    "voltage": ["电压"],
    "communication": ["通信", "通讯"],
}
ALARM_PARAMETER_HINTS = {
    "E101": {"temperature"},
    "E201": {"vibration"},
    "E203": {"current", "vibration"},
    "E404": {"communication"},
}
DISCLAIMER = (
    "\u672c\u8bca\u65ad\u7ed3\u679c\u7531\u8bbe\u5907\u6570\u636e\u548c"
    "\u77e5\u8bc6\u5e93\u4fe1\u606f\u8f85\u52a9\u751f\u6210\uff0c"
    "\u4ec5\u4f9b\u6392\u67e5\u53c2\u8003\u3002\u6d89\u53ca"
    "\u9ad8\u6e29\u3001\u7535\u6c14\u3001\u673a\u68b0\u6216"
    "\u5b89\u5168\u98ce\u9669\u65f6\uff0c\u8bf7\u505c\u6b62"
    "\u8bbe\u5907\u5e76\u7531\u4e13\u4e1a\u4eba\u5458\u73b0\u573a\u786e\u8ba4\u3002"
)
LLM_UNAVAILABLE_WARNING = "智能诊断服务暂时不可用，已根据设备数据和知识库信息生成保守结果。"
logger = logging.getLogger(__name__)


def parse_agent_query(request: AgentDiagnoseRequest) -> ParsedAgentQuery:
    """Parse an agent query using deterministic rules."""

    query = request.query
    device_code = request.device_code or _extract_device_code(query)
    fault_codes = _extract_fault_codes(query)
    has_fault_symptom = _has_fault_symptom(query)
    intent = _classify_intent(query, device_code, fault_codes, has_fault_symptom)

    return ParsedAgentQuery(
        original_query=query,
        device_code=device_code,
        fault_codes=fault_codes,
        intent=intent,
        has_fault_symptom=has_fault_symptom,
    )


def build_tool_plan(
    request: AgentDiagnoseRequest,
    parsed_query: ParsedAgentQuery,
) -> AgentToolPlan:
    """Build a deterministic tool plan for one query."""

    use_device_tool = False
    use_knowledge_tool = False
    reason = "No tool needed."

    if parsed_query.intent in {"device_status_query", "device_info_query"}:
        use_device_tool = parsed_query.device_code is not None
        reason = f"Intent is {parsed_query.intent}."
    elif parsed_query.intent == "knowledge_query":
        use_knowledge_tool = True
        reason = "Query asks for general fault knowledge."
    elif parsed_query.intent == "diagnosis":
        use_device_tool = parsed_query.device_code is not None
        use_knowledge_tool = True
        reason = "Query includes device context and fault symptoms."

    if not request.include_device_status:
        use_device_tool = False

    if not request.include_knowledge:
        use_knowledge_tool = False

    if parsed_query.device_code is None:
        use_device_tool = False

    return AgentToolPlan(
        use_device_tool=use_device_tool,
        use_knowledge_tool=use_knowledge_tool,
        device_code=parsed_query.device_code if use_device_tool else None,
        knowledge_query=request.query if use_knowledge_tool else None,
        reason=reason,
    )


def build_agent_context(
    db: Session,
    request: AgentDiagnoseRequest,
    history_messages: list[Message] | None = None,
) -> AgentWorkflowContext:
    """Run deterministic parsing, planning, and at most one call per tool."""

    parsed_query = parse_agent_query(request)
    tool_plan = build_tool_plan(request, parsed_query)
    device_result: DeviceStatusToolResult | None = None
    knowledge_result: KnowledgeSearchToolResult | None = None
    tools_attempted: list[str] = []
    tools_succeeded: list[str] = []
    warnings: list[str] = []

    if tool_plan.use_device_tool and tool_plan.device_code is not None:
        tools_attempted.append("get_device_status")
        device_result = run_get_device_status_tool(
            db,
            DeviceStatusToolInput(device_code=tool_plan.device_code),
        )
        warnings.extend(device_result.warnings)
        if device_result.ok:
            tools_succeeded.append("get_device_status")
        else:
            warnings.append("设备状态查询工具暂时不可用。")

    if tool_plan.use_knowledge_tool and tool_plan.knowledge_query is not None:
        tools_attempted.append("search_knowledge")
        knowledge_query = _build_knowledge_query(
            tool_plan.knowledge_query,
            device_result,
            history_messages=history_messages,
        )
        knowledge_result = run_search_knowledge_tool(
            KnowledgeSearchToolInput(
                query=knowledge_query,
                top_k=request.knowledge_top_k,
            )
        )
        warnings.extend(knowledge_result.warnings)
        if knowledge_result.ok:
            tools_succeeded.append("search_knowledge")
        else:
            warnings.append("知识库检索工具暂时不可用。")

    allowed_sources = (
        [result.source for result in knowledge_result.results]
        if knowledge_result is not None and knowledge_result.ok
        else []
    )

    return AgentWorkflowContext(
        request=request,
        parsed_query=parsed_query,
        tool_plan=tool_plan,
        device_tool_result=device_result,
        knowledge_tool_result=knowledge_result,
        tools_attempted=tools_attempted,
        tools_succeeded=tools_succeeded,
        allowed_sources=allowed_sources,
        minimum_risk_level=calculate_minimum_risk_level(device_result),
        warnings=warnings,
    )


def run_agent_diagnosis(
    db: Session,
    request: AgentDiagnoseRequest,
    llm_provider: LLMProvider,
) -> AgentDiagnoseResponse:
    """Compatibility entry backed by the enterprise DiagnosisOrchestrator."""

    from app.agent.orchestrator import DiagnosisOrchestrator

    orchestrator = DiagnosisOrchestrator(db=db, llm_provider=llm_provider)
    return orchestrator.run_single(request, mode="workflow")


def calculate_minimum_risk_level(
    device_result: DeviceStatusToolResult | None,
) -> str:
    """Calculate the deterministic lower bound for risk level."""

    if device_result is None or not device_result.ok or not device_result.recent_alarms:
        return "unknown"

    highest = "unknown"
    for alarm in device_result.recent_alarms:
        level = alarm.alarm_level.lower()
        if level in RISK_ORDER and RISK_ORDER[level] > RISK_ORDER[highest]:
            highest = level

    return highest


def _assemble_response(
    context: AgentWorkflowContext,
    problem_summary: str,
    risk_level: str,
    possible_causes: list[str],
    recommended_actions: list[str],
    draft_warnings: list[str] | None = None,
) -> AgentDiagnoseResponse:
    device_result = context.device_tool_result
    has_device_result = device_result is not None and device_result.ok

    return AgentDiagnoseResponse(
        problem_summary=problem_summary,
        device=device_result.device if has_device_result else None,
        device_status=(
            device_result.latest_runtime_data if has_device_result else None
        ),
        recent_alarms=device_result.recent_alarms if has_device_result else [],
        risk_level=risk_level,
        possible_causes=possible_causes,
        recommended_actions=recommended_actions,
        sources=_dedupe(context.allowed_sources),
        tools_used=_dedupe(context.tools_succeeded),
        warnings=_dedupe([*context.warnings, *(draft_warnings or [])]),
        disclaimer=DISCLAIMER,
    )


def _build_llm_fallback_response(
    context: AgentWorkflowContext,
) -> AgentDiagnoseResponse:
    has_evidence = _has_tool_evidence(context)
    risk_level = context.minimum_risk_level if has_evidence else "unknown"

    if has_evidence:
        problem_summary = _fallback_summary(context)
        recommended_actions = (
            _high_risk_actions()
            if risk_level in {"high", "critical"}
            else _general_fallback_actions()
        )
    else:
        problem_summary = "Unable to complete diagnosis because no usable tool data is available."
        recommended_actions = _no_data_actions()

    return _assemble_response(
        context=context,
        problem_summary=problem_summary,
        risk_level=risk_level,
        possible_causes=[],
        recommended_actions=recommended_actions,
        draft_warnings=[LLM_UNAVAILABLE_WARNING],
    )


def _fallback_summary(context: AgentWorkflowContext) -> str:
    parts = [
        (
            "当前 AI 诊断服务暂时不可用，以下结果基于设备数据和知识库信息生成。"
        )
    ]
    device_result = context.device_tool_result
    if device_result is not None and device_result.ok and device_result.device is not None:
        parts.append(f"设备编号：{device_result.device.device_code}。")
    if device_result is not None and device_result.ok and device_result.recent_alarms:
        alarm_codes = ", ".join(alarm.alarm_code for alarm in device_result.recent_alarms)
        parts.append(f"近期未解决报警：{alarm_codes}。")
    if context.allowed_sources:
        parts.append("已检索到相关知识库片段。")
    return " ".join(parts)


def _apply_no_evidence_risk_guard(
    context: AgentWorkflowContext,
    risk_level: str,
) -> str:
    if not _has_tool_evidence(context):
        return "unknown"
    return risk_level


def _has_tool_evidence(context: AgentWorkflowContext) -> bool:
    device_result = context.device_tool_result
    has_device_evidence = (
        device_result is not None
        and device_result.ok
        and (
            device_result.device is not None
            or device_result.latest_runtime_data is not None
            or bool(device_result.recent_alarms)
        )
    )
    has_knowledge_evidence = (
        context.knowledge_tool_result is not None
        and context.knowledge_tool_result.ok
        and bool(context.knowledge_tool_result.results)
    )
    return has_device_evidence or has_knowledge_evidence


def _high_risk_actions() -> list[str]:
    return [
        "Stop high-load operation.",
        "Check whether the equipment requires a safe shutdown.",
        "Inspect cooling, power supply, sensors, and alarm records.",
        "Contact professional maintenance personnel for on-site confirmation.",
    ]


def _general_fallback_actions() -> list[str]:
    return [
        "Review the available equipment status and alarm records.",
        "Compare the symptom with retrieved knowledge sources.",
        "Collect updated runtime data before taking major maintenance actions.",
        "Ask professional maintenance personnel to confirm uncertain findings.",
    ]


def _no_data_actions() -> list[str]:
    return [
        "请提供设备编号。",
        "请提供报警码。",
        "请提供最新运行数据或故障现象。",
        "请现场人员进行基础检查。",
    ]


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


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


def _extract_device_code(query: str) -> str | None:
    match = DEVICE_CODE_PATTERN.search(query)
    return match.group(0).upper() if match else None


def _extract_fault_codes(query: str) -> list[str]:
    codes = []
    for match in FAULT_CODE_PATTERN.finditer(query):
        code = match.group(0).upper()
        if not code.startswith("DEV-") and code not in codes:
            codes.append(code)
    return codes


def _has_fault_symptom(query: str) -> bool:
    return any(keyword in query for keyword in FAULT_SYMPTOM_KEYWORDS)


def _classify_intent(
    query: str,
    device_code: str | None,
    fault_codes: list[str],
    has_fault_symptom: bool,
) -> str:
    has_status_keyword = any(keyword in query for keyword in STATUS_KEYWORDS)
    has_info_keyword = any(keyword in query for keyword in INFO_KEYWORDS)

    if device_code is not None and (fault_codes or has_fault_symptom):
        return "diagnosis"

    if device_code is not None and has_info_keyword:
        return "device_info_query"

    if device_code is not None and has_status_keyword:
        return "device_status_query"

    if fault_codes or has_fault_symptom:
        return "knowledge_query"

    return "small_talk_or_unknown"


def _build_knowledge_query(
    original_query: str,
    device_result: DeviceStatusToolResult | None,
    history_messages: list[Message] | None = None,
) -> str:
    query = _build_history_augmented_query(original_query, history_messages)
    alarm_terms: list[str] = []
    device_type: str | None = None
    if device_result is not None and device_result.ok:
        if device_result.device is not None:
            device_type = device_result.device.device_type
        for alarm in device_result.recent_alarms:
            alarm_term = _format_alarm_knowledge_term(alarm)
            if alarm_term not in alarm_terms:
                alarm_terms.append(alarm_term)

    concerns = _extract_query_parameter_concerns(query)
    if concerns:
        alarm_terms = [
            term for term in alarm_terms if _alarm_term_matches_query_concern(term, concerns)
        ]

    if not alarm_terms:
        return query

    return _join_knowledge_query_parts(
        [
            " ".join(alarm_terms),
            query,
            device_type,
            "maintenance handling steps",
        ]
    )


def _format_alarm_knowledge_term(alarm: ToolAlarmRecord) -> str:
    return _join_knowledge_query_parts([alarm.alarm_code, alarm.message])


def _extract_query_parameter_concerns(query: str) -> set[str]:
    return {
        parameter
        for parameter, keywords in QUERY_PARAMETER_KEYWORDS.items()
        if any(keyword in query for keyword in keywords)
    }


def _alarm_term_matches_query_concern(
    alarm_term: str,
    concerns: set[str],
) -> bool:
    if not concerns:
        return True

    normalized_term = alarm_term.upper()
    for alarm_code, parameters in ALARM_PARAMETER_HINTS.items():
        if alarm_code in normalized_term and parameters & concerns:
            return True

    return any(
        keyword in alarm_term
        for parameter in concerns
        for keyword in QUERY_PARAMETER_KEYWORDS.get(parameter, [])
    )


def _join_knowledge_query_parts(parts: list[str | None]) -> str:
    joined_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        normalized = " ".join(part.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        joined_parts.append(normalized)

    return " ".join(joined_parts)


def _build_history_augmented_query(
    original_query: str,
    history_messages: list[Message] | None,
) -> str:
    history_queries = [
        message.content.strip()
        for message in history_messages or []
        if message.role == "user" and message.content.strip()
    ]
    if not history_queries:
        return original_query

    return " ".join([*history_queries[-3:], original_query])
