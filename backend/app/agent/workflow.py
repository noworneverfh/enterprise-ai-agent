import re

from sqlalchemy.orm import Session

from app.agent.tools import run_get_device_status_tool, run_search_knowledge_tool
from app.schemas.agent import (
    AgentDiagnoseRequest,
    AgentToolPlan,
    AgentWorkflowContext,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ParsedAgentQuery,
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
            warnings.append("Device status tool unavailable.")

    if tool_plan.use_knowledge_tool and tool_plan.knowledge_query is not None:
        tools_attempted.append("search_knowledge")
        knowledge_query = _build_knowledge_query(tool_plan.knowledge_query, device_result)
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
            warnings.append("Knowledge search tool unavailable.")

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
) -> str:
    alarm_codes: list[str] = []
    if device_result is not None and device_result.ok:
        for alarm in device_result.recent_alarms:
            if alarm.alarm_code not in alarm_codes:
                alarm_codes.append(alarm.alarm_code)

    if not alarm_codes:
        return original_query

    return f"{original_query} {' '.join(alarm_codes)}"
