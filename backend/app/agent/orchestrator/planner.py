from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.agent.tool_choice_router import route_tool_choices
from app.schemas.agent import AgentDiagnoseRequest, MultiDeviceRiskRequest


PlanMode = Literal["single_device", "fleet", "small_talk"]


@dataclass(frozen=True)
class ToolPlan:
    mode: PlanMode
    tool_names: list[str]
    device_code: str | None = None
    include_knowledge: bool = True
    knowledge_top_k: int = 5
    reason: str = ""
    fault_codes: list[str] = field(default_factory=list)


FAULT_OR_KNOWLEDGE_KEYWORDS = (
    "\u62a5\u8b66",  # 报警
    "\u6545\u969c",  # 故障
    "\u5f02\u5e38",  # 异常
    "\u539f\u56e0",  # 原因
    "\u5904\u7406",  # 处理
    "\u7ef4\u4fee",  # 维修
    "\u6e29\u5ea6",  # 温度
    "\u632f\u52a8",  # 振动
    "\u7535\u6d41",  # 电流
    "\u7535\u538b",  # 电压
    "\u901a\u4fe1",  # 通信
    "\u600e\u4e48",  # 怎么
    "\u5982\u4f55",  # 如何
)


class IntentPlanner:
    """Rule-based enterprise planner for predictable tool use."""

    def plan_single(self, request: AgentDiagnoseRequest) -> ToolPlan:
        normalized_query = _query_with_device(request)
        routed = route_tool_choices(normalized_query).tool_names
        device_code = request.device_code or _extract_device_code(request.query)
        fault_codes = _extract_fault_codes(request.query)

        tool_names: list[str] = []
        if request.include_device_status and device_code:
            tool_names.extend(["get_device_status", "get_device_alarms"])

        for tool_name in routed:
            if tool_name not in tool_names:
                tool_names.append(tool_name)

        if not request.include_knowledge:
            tool_names = [name for name in tool_names if name != "search_knowledge"]

        if (
            request.include_knowledge
            and _is_fault_or_knowledge_query(request.query)
            and "search_knowledge" not in tool_names
        ):
            tool_names.append("search_knowledge")

        mode: PlanMode = "single_device" if tool_names else "small_talk"
        return ToolPlan(
            mode=mode,
            tool_names=tool_names,
            device_code=device_code,
            include_knowledge=request.include_knowledge,
            knowledge_top_k=request.knowledge_top_k,
            reason=_plan_reason(request.query, tool_names),
            fault_codes=fault_codes,
        )

    def plan_fleet(self, request: MultiDeviceRiskRequest) -> ToolPlan:
        tool_names = ["list_devices", "get_device_status", "get_device_alarms"]
        if request.include_knowledge:
            tool_names.append("search_knowledge")
        return ToolPlan(
            mode="fleet",
            tool_names=tool_names,
            include_knowledge=request.include_knowledge,
            knowledge_top_k=request.knowledge_top_k,
            reason="Fleet risk analysis requires device, alarm, runtime, and knowledge evidence.",
            fault_codes=_extract_fault_codes(request.query),
        )


def _query_with_device(request: AgentDiagnoseRequest) -> str:
    if request.device_code and request.device_code not in request.query:
        return f"{request.device_code} {request.query}"
    return request.query


def _extract_device_code(query: str) -> str | None:
    match = re.search(r"\bDEV-\d+\b", query, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _extract_fault_codes(query: str) -> list[str]:
    result: list[str] = []
    for match in re.finditer(r"\b[A-Z]\d{3,}\b", query, re.IGNORECASE):
        code = match.group(0).upper()
        if code not in result:
            result.append(code)
    return result


def _is_fault_or_knowledge_query(query: str) -> bool:
    if _extract_fault_codes(query):
        return True
    return any(keyword in query for keyword in FAULT_OR_KNOWLEDGE_KEYWORDS)


def _plan_reason(query: str, tool_names: list[str]) -> str:
    if not tool_names:
        return "No device, alarm, or fault intent was detected."
    if "search_knowledge" in tool_names and any(
        tool in tool_names for tool in ("get_device_status", "get_device_alarms")
    ):
        return "Device context and fault intent require tool evidence plus knowledge retrieval."
    if "search_knowledge" in tool_names:
        return "Fault knowledge query requires knowledge retrieval."
    return "Device status query requires device tool evidence."
