import json
import logging
import re
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.tool_choice_router import build_openai_tool_choice, route_tool_choices
from app.agent.tool_executor import ToolCallExecutor
from app.agent.tool_registry import AgentToolDefinition, list_agent_tools
from app.agent import trace as agent_trace
from app.agent.workflow import DISCLAIMER, calculate_minimum_risk_level
from app.conversation import service as conversation_service
from app.conversation.models import Conversation, Message
from app.llm.base import LLMMessage
from app.schemas.agent import (
    AgentDiagnoseRequest,
    AgentDiagnoseResponse,
    AgentDiagnosisDraft,
    DeviceStatusToolResult,
    DeviceAlarmsToolResult,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolRuntimeData,
    enforce_minimum_risk_level,
)


MAX_TOOL_ITERATIONS = 5
logger = logging.getLogger(__name__)
RUNTIME_FALLBACK_WARNING = "智能诊断运行时暂时不可用，已根据现有工具结果生成保守结果。"
FINAL_LLM_UNAVAILABLE_WARNING = (
    "最终智能分析暂时不可用，当前结果根据已获取的设备数据和知识库信息生成。"
)
RUNTIME_RISK_LEVEL_ALIASES = {
    "低风险": "low",
    "低": "low",
    "中风险": "medium",
    "中": "medium",
    "一般": "medium",
    "高风险": "high",
    "较高": "high",
    "严重风险": "critical",
    "严重": "critical",
    "危险": "critical",
    "未知": "unknown",
}
RUNTIME_DRAFT_ALLOWED_FIELDS = {
    "problem_summary",
    "risk_level",
    "possible_causes",
    "recommended_actions",
    "warnings",
}
RUNTIME_RESPONSE_LOG_PREVIEW_LIMIT = 1000
RUNTIME_PARAMETER_LIMITS = {
    "temperature": {"max": 60.0},
    "vibration": {"max": 0.4},
    "current": {"max": 10.0},
    "voltage": {"min": 200.0, "max": 245.0},
}
QUERY_PARAMETER_KEYWORDS = {
    "temperature": ["温度", "过热", "升温", "高温"],
    "vibration": ["振动", "震动"],
    "current": ["电流"],
    "voltage": ["电压"],
    "communication": ["通信", "通讯"],
}
PARAMETER_LABELS = {
    "temperature": "温度",
    "vibration": "振动",
    "current": "电流",
    "voltage": "电压",
    "communication": "通信",
}
ALARM_PARAMETER_HINTS = {
    "E101": {"temperature"},
    "E201": {"vibration"},
    "E203": {"current", "vibration"},
    "E404": {"communication"},
}


@dataclass(frozen=True)
class AgentRuntimeToolCall:
    """Tool call requested by an LLM runtime response."""

    id: str | None
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentRuntimeLLMResponse:
    """Minimal LLM response shape needed by the tool-calling runtime."""

    content: str | None = None
    tool_calls: list[AgentRuntimeToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRuntimeResult:
    """Final result returned by the tool-calling runtime."""

    success: bool
    content: str | None
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    error: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class RuntimeDraftParseResult:
    """Runtime final draft parse result with a stable failure reason."""

    draft: AgentDiagnosisDraft | None
    fallback_reason: str | None = None


class ToolCallingProvider(Protocol):
    """Provider protocol for the experimental tool-calling runtime."""

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> AgentRuntimeLLMResponse:
        """Return either final content or one or more tool calls."""


class AgentRuntime:
    """Minimal agent loop for future LLM-driven tool calling."""

    def __init__(
        self,
        llm_provider: ToolCallingProvider,
        tool_executor: ToolCallExecutor,
        tool_registry: list[AgentToolDefinition] | None = None,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.tool_registry = tool_registry or list_agent_tools()
        self.max_tool_iterations = max_tool_iterations
        self._sleep = sleep_func

    def run(self, messages: list[LLMMessage | dict[str, Any]]) -> AgentRuntimeResult:
        runtime_messages = [self._message_to_dict(message) for message in messages]
        tools = [tool.openai_tool_schema() for tool in self.tool_registry]
        tool_results: list[dict[str, Any]] = []
        forced_tool_names = route_tool_choices(
            self._latest_user_query(runtime_messages)
        ).tool_names
        agent_trace.record_router_selection(forced_tool_names)
        forced_tool_index = 0

        for _iteration in range(self.max_tool_iterations):
            final_response_stage = bool(tool_results)
            if final_response_stage:
                request_tools = []
                tool_choice = "auto"
            else:
                request_tools = self._select_request_tools(tools, forced_tool_names)
                tool_choice = self._build_request_tool_choice(forced_tool_names)
            self._log_tool_round_payload(
                runtime_messages,
                request_tools,
                tool_choice,
            )
            try:
                response = self.llm_provider.complete_with_tools(
                    messages=runtime_messages,
                    tools=request_tools,
                    tool_choice=tool_choice,
                )
            except Exception:
                if self._is_final_response_stage(tool_results):
                    try:
                        logger.exception(
                            "Agent runtime final LLM call failed; retrying once."
                        )
                        self._sleep(0.5)
                        self._log_tool_round_payload(
                            runtime_messages,
                            request_tools,
                            tool_choice,
                        )
                        response = self.llm_provider.complete_with_tools(
                            messages=runtime_messages,
                            tools=request_tools,
                            tool_choice=tool_choice,
                        )
                    except Exception:
                        logger.exception("Agent runtime final LLM retry failed.")
                        return AgentRuntimeResult(
                            success=False,
                            content="智能分析服务暂时不可用，无法完成本次推理。",
                            messages=runtime_messages,
                            tool_results=tool_results,
                            error="final_llm_failed",
                            fallback_reason="final_llm_failed",
                        )
                else:
                    logger.exception("Agent runtime LLM call failed.")
                    error_code = "final_llm_failed" if tool_results else "llm_failed"
                    return AgentRuntimeResult(
                        success=False,
                        content="智能分析服务暂时不可用，无法完成本次推理。",
                        messages=runtime_messages,
                        tool_results=tool_results,
                        error=error_code,
                        fallback_reason=error_code,
                    )

            if not response.tool_calls:
                return AgentRuntimeResult(
                    success=True,
                    content=response.content or "",
                    messages=runtime_messages,
                    tool_results=tool_results,
                    error=None,
                )

            runtime_messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        self._tool_call_to_openai_dict(tool_call)
                        for tool_call in response.tool_calls
                    ],
                }
            )

            for tool_call in response.tool_calls:
                tool_result = self._execute_tool_call(
                    tool_call,
                    prior_tool_results=tool_results,
                    messages=runtime_messages,
                )
                tool_results.append(tool_result)
                agent_trace.record_tool_result(tool_result)
                if (
                    forced_tool_index < len(forced_tool_names)
                    and tool_call.name == forced_tool_names[forced_tool_index]
                ):
                    forced_tool_index += 1
                runtime_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            self._complete_missing_forced_tools(
                runtime_messages,
                tool_results,
                forced_tool_names,
            )
            intent_mismatch_content = self._build_intent_mismatch_final_content(
                runtime_messages,
                tool_results,
            )
            if intent_mismatch_content is not None:
                return AgentRuntimeResult(
                    success=True,
                    content=intent_mismatch_content,
                    messages=runtime_messages,
                    tool_results=tool_results,
                    error=None,
                )

        return AgentRuntimeResult(
            success=False,
            content="Tool calling stopped because the maximum number of iterations was reached.",
            messages=runtime_messages,
            tool_results=tool_results,
            error="max_tool_iterations_exceeded",
            fallback_reason="max_tool_iterations_exceeded",
        )

    def _execute_tool_call(
        self,
        tool_call: AgentRuntimeToolCall,
        prior_tool_results: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        trace_context: dict[str, str] = {}
        if tool_call.name == "search_knowledge":
            arguments, trace_context, warnings = self._enrich_search_knowledge_arguments(
                tool_call.arguments,
                latest_user_query=self._latest_user_query(messages or []),
                tool_results=prior_tool_results or [],
            )
            logger.info(
                "Runtime search_knowledge input. query=%s device_code=%s alarm_code=%s",
                arguments.get("query"),
                trace_context.get("device_code"),
                trace_context.get("alarm_code"),
            )
            tool_call = AgentRuntimeToolCall(
                id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
            )

        try:
            tool_result = self.tool_executor.execute(tool_call.name, tool_call.arguments)
            if (
                tool_call.name == "search_knowledge"
                and trace_context
                and isinstance(tool_result.get("result"), dict)
            ):
                tool_result = dict(tool_result)
                result_payload = dict(tool_result["result"])
                result_payload["_trace"] = trace_context
                if warnings:
                    result_payload["warnings"] = _dedupe(
                        [
                            *(
                                result_payload.get("warnings")
                                if isinstance(result_payload.get("warnings"), list)
                                else []
                            ),
                            *warnings,
                        ]
                    )
                tool_result["result"] = result_payload
            return tool_result
        except Exception:
            logger.exception("Agent runtime tool execution failed.")
            return {
                "tool_name": tool_call.name,
                "success": False,
                "result": {},
                "error": "tool_execution_failed",
            }

    def _message_to_dict(self, message: LLMMessage | dict[str, Any]) -> dict[str, Any]:
        if isinstance(message, LLMMessage):
            return message.model_dump()

        return dict(message)

    def _tool_call_to_openai_dict(
        self,
        tool_call: AgentRuntimeToolCall,
    ) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
            },
        }

    def _complete_missing_forced_tools(
        self,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        forced_tool_names: list[str],
    ) -> None:
        if len(forced_tool_names) < 2:
            return

        executed_tool_names = {
            result.get("tool_name")
            for result in tool_results
            if isinstance(result.get("tool_name"), str)
        }
        missing_tool_names = [
            tool_name
            for tool_name in forced_tool_names
            if tool_name not in executed_tool_names
        ]
        if not missing_tool_names:
            return

        for tool_name in missing_tool_names:
            tool_call = self._build_missing_tool_call(tool_name, messages, tool_results)
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [self._tool_call_to_openai_dict(tool_call)],
                }
            )
            logger.info(
                "Agent runtime completing missing forced tool. tool_name=%s arguments=%s",
                tool_call.name,
                self._safe_argument_preview(tool_call.arguments),
            )
            tool_result = self._execute_tool_call(
                tool_call,
                prior_tool_results=tool_results,
                messages=messages,
            )
            tool_results.append(tool_result)
            agent_trace.record_tool_result(tool_result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    def _build_missing_tool_call(
        self,
        tool_name: str,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> AgentRuntimeToolCall:
        latest_user_query = self._latest_user_query(messages)
        if tool_name == "get_device_status":
            device_code_match = re.search(r"\bDEV-\d+\b", latest_user_query, re.IGNORECASE)
            inferred_device_code = _infer_device_code_from_tool_results(tool_results)
            arguments = {
                "device_code": (
                    device_code_match.group(0).upper()
                    if device_code_match is not None
                    else inferred_device_code or ""
                )
            }
        elif tool_name == "get_device_alarms":
            device_code_match = re.search(r"\bDEV-\d+\b", latest_user_query, re.IGNORECASE)
            arguments = {
                "device_code": (
                    device_code_match.group(0).upper()
                    if device_code_match is not None
                    else None
                ),
                "limit": 20,
                "unresolved_only": True,
            }
        elif tool_name == "search_knowledge":
            knowledge_query, _warnings = self._build_knowledge_query_from_tool_results(
                latest_user_query,
                tool_results,
            )
            arguments = {
                "query": knowledge_query,
                "top_k": 5,
            }
        else:
            arguments = {}

        return AgentRuntimeToolCall(
            id=f"runtime-call-{tool_name}",
            name=tool_name,
            arguments=arguments,
        )

    def _knowledge_query_from_user_message(self, latest_user_query: str) -> str:
        for line in latest_user_query.splitlines():
            stripped = line.strip()
            if stripped.startswith("用户问题:"):
                return stripped.removeprefix("用户问题:").strip()

        return latest_user_query.strip()

    def _enrich_search_knowledge_arguments(
        self,
        arguments: dict[str, Any],
        *,
        latest_user_query: str,
        tool_results: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, str], list[str]]:
        enriched_arguments = dict(arguments)
        base_query = str(
            enriched_arguments.get("query")
            or self._knowledge_query_from_user_message(latest_user_query)
        ).strip()
        warnings: list[str] = []
        if "maintenance handling steps" not in base_query:
            base_query, warnings = self._build_knowledge_query_from_tool_results(
                latest_user_query,
                tool_results,
                base_query=base_query,
            )
        enriched_arguments["query"] = base_query
        enriched_arguments.setdefault("top_k", 5)
        return enriched_arguments, self._build_knowledge_trace_context(
            enriched_arguments["query"],
            tool_results,
        ), warnings

    def _build_knowledge_query_from_tool_results(
        self,
        latest_user_query: str,
        tool_results: list[dict[str, Any]],
        *,
        base_query: str | None = None,
    ) -> tuple[str, list[str]]:
        query = (base_query or self._knowledge_query_from_user_message(latest_user_query)).strip()
        alarm_terms, device_type = self._knowledge_terms_from_tool_results(tool_results)
        concerns = _extract_query_parameter_concerns(query)
        warnings = _build_query_alarm_mismatch_warnings(query, concerns, alarm_terms, tool_results)
        if concerns:
            alarm_terms = [
                term
                for term in alarm_terms
                if _alarm_term_matches_query_concern(term, concerns)
            ]
        if not alarm_terms:
            return query, warnings

        return _join_query_parts(
            [
                " ".join(alarm_terms),
                query,
                device_type,
                "maintenance handling steps",
            ]
        ), warnings

    def _knowledge_terms_from_tool_results(
        self,
        tool_results: list[dict[str, Any]],
    ) -> tuple[list[str], str | None]:
        return _knowledge_terms_from_runtime_tool_results(tool_results)

    def _build_knowledge_trace_context(
        self,
        query: str,
        tool_results: list[dict[str, Any]],
    ) -> dict[str, str]:
        context: dict[str, str] = {"query": query}
        device_code = _infer_device_code_from_tool_results(tool_results)
        if device_code:
            context["device_code"] = device_code

        alarm_codes: list[str] = []
        for term, _device_type in [self._knowledge_terms_from_tool_results(tool_results)]:
            for alarm_term in term:
                match = re.search(r"\bE\d{3,}\b", alarm_term, re.IGNORECASE)
                if match and match.group(0).upper() in query.upper():
                    alarm_codes.append(match.group(0).upper())
        if alarm_codes:
            context["alarm_code"] = ",".join(_dedupe(alarm_codes))

        return context

    def _latest_user_query(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                return content if isinstance(content, str) else ""

        return ""

    def _select_request_tools(
        self,
        tools: list[dict[str, Any]],
        forced_tool_names: list[str],
    ) -> list[dict[str, Any]]:
        if not forced_tool_names:
            return tools

        forced_tool_name_set = set(forced_tool_names)
        selected_tools = [
            tool
            for tool in tools
            if tool.get("function", {}).get("name") in forced_tool_name_set
        ]
        return selected_tools or tools

    def _build_request_tool_choice(
        self,
        forced_tool_names: list[str],
    ) -> str | dict[str, Any]:
        if len(forced_tool_names) == 1:
            return build_openai_tool_choice(forced_tool_names[0])

        return "auto"

    def _log_tool_round_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> None:
        logger.info(
            "Runtime tool round payload: messages_roles=%s tool_calls=%s "
            "tools=%s tool_choice=%s",
            [message.get("role") for message in messages],
            self._summarize_message_tool_calls(messages),
            [
                tool.get("function", {}).get("name")
                for tool in tools
                if isinstance(tool.get("function"), dict)
            ],
            tool_choice,
        )

    def _summarize_message_tool_calls(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "assistant":
                tool_calls = message.get("tool_calls")
                if not isinstance(tool_calls, list):
                    continue
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    arguments = (
                        function.get("arguments")
                        if isinstance(function, dict)
                        else None
                    )
                    summaries.append(
                        {
                            "tool_call_id": tool_call.get("id"),
                            "name": (
                                function.get("name")
                                if isinstance(function, dict)
                                else None
                            ),
                            "arguments": self._safe_argument_preview(arguments),
                        }
                    )
            elif role == "tool":
                summaries.append(
                    {
                        "tool_call_id": message.get("tool_call_id"),
                        "name": message.get("name"),
                        "arguments": None,
                    }
                )

        return summaries

    def _safe_argument_preview(self, arguments: object) -> object:
        if not isinstance(arguments, str):
            return arguments

        if len(arguments) > 500:
            return f"{arguments[:500]}..."

        return arguments

    def _is_final_response_stage(
        self,
        tool_results: list[dict[str, Any]],
    ) -> bool:
        return bool(tool_results)

    def _build_intent_mismatch_final_content(
        self,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> str | None:
        latest_query = self._knowledge_query_from_user_message(self._latest_user_query(messages))
        mismatch = _detect_intent_mismatch(latest_query, tool_results)
        if mismatch is None:
            return None

        return json.dumps(
            {
                "problem_summary": (
                    f"用户关注：{mismatch['concern']}异常。"
                    f"当前状态：未检测到{mismatch['concern']}异常。"
                    f"当前设备异常：{mismatch['current_alarms']}。"
                ),
                "risk_level": "unknown",
                "possible_causes": [],
                "recommended_actions": [
                    f"请确认是否需要分析{mismatch['concern']}异常。",
                    "如果需要分析温度异常，请重新提交温度诊断。",
                ],
                "warnings": [
                    (
                        f"用户关注问题与当前设备真实异常不一致："
                        f"未发现{mismatch['concern']}异常。"
                    )
                ],
            },
            ensure_ascii=False,
        )


def run_agent_runtime_diagnosis(
    db: Session,
    request: AgentDiagnoseRequest,
    llm_provider: ToolCallingProvider,
) -> AgentDiagnoseResponse:
    """Compatibility entry backed by the enterprise DiagnosisOrchestrator."""

    if not hasattr(llm_provider, "complete_structured"):
        return _run_agent_runtime_diagnosis_tool_calling_compat(
            db=db,
            request=request,
            llm_provider=llm_provider,
        )

    from app.agent.orchestrator import DiagnosisOrchestrator

    orchestrator = DiagnosisOrchestrator(
        db=db,
        llm_provider=llm_provider,  # type: ignore[arg-type]
    )
    return orchestrator.run_single(request, mode="runtime")


def _run_agent_runtime_diagnosis_tool_calling_compat(
    db: Session,
    request: AgentDiagnoseRequest,
    llm_provider: ToolCallingProvider,
) -> AgentDiagnoseResponse:
    """Keep legacy tool-calling tests and custom providers working."""

    agent_trace.start_agent_trace(
        mode="runtime",
        query=request.query,
        device_code=request.device_code,
    )
    conversation = _get_request_conversation(db, request)
    history_messages = _get_request_history(db, request, conversation)
    _save_user_message(db, conversation, request)

    route = route_tool_choices(_route_query_from_request(request))
    if _is_alarm_overview_route(route.tool_names):
        agent_trace.record_router_selection(route.tool_names)
        executor = ToolCallExecutor(db)
        runtime_result = _run_alarm_overview_query(request, executor)
        tool_state = _collect_tool_state(runtime_result.tool_results)
        runtime_result = _run_final_llm_from_tool_results(
            request=request,
            runtime_result=runtime_result,
            llm_provider=llm_provider,
        )
    else:
        runtime = AgentRuntime(
            llm_provider=llm_provider,
            tool_executor=ToolCallExecutor(db),
        )
        runtime_result = runtime.run(_build_runtime_messages(request, history_messages))
        tool_state = _collect_tool_state(runtime_result.tool_results)

    if not runtime_result.success:
        agent_trace.record_llm_final_status(
            status="fallback",
            fallback_reason=runtime_result.fallback_reason or runtime_result.error,
        )
        response = _build_runtime_fallback_response(request, runtime_result, tool_state)
        _save_assistant_message(db, conversation, response)
        return response

    parse_result = _parse_runtime_draft_with_reason(runtime_result.content)
    if parse_result.draft is None:
        runtime_result = AgentRuntimeResult(
            success=runtime_result.success,
            content=runtime_result.content,
            messages=runtime_result.messages,
            tool_results=runtime_result.tool_results,
            error=runtime_result.error,
            fallback_reason=parse_result.fallback_reason,
        )
        agent_trace.record_llm_final_status(
            status="fallback",
            fallback_reason=parse_result.fallback_reason,
        )
        response = _build_runtime_fallback_response(request, runtime_result, tool_state)
        _save_assistant_message(db, conversation, response)
        return response

    response = _build_runtime_response_from_draft(
        draft=parse_result.draft,
        tool_state=tool_state,
    )
    agent_trace.record_llm_final_status(status="success")
    _save_assistant_message(db, conversation, response)
    return response


def _build_runtime_messages(
    request: AgentDiagnoseRequest,
    history_messages: list[Message],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an enterprise equipment diagnosis agent. Use tools when "
                "device status or maintenance knowledge is needed. Tool selection "
                "rules. Mandatory Tool Usage Rules: If the user query contains "
                "DEV-xxx plus 状态, 当前, 在线, 运行情况, or 设备信息, you MUST call "
                "get_device_status before answering. If the user query contains "
                "both DEV-xxx and an alarm code, you MUST call get_device_status, "
                "get_device_alarms, and search_knowledge before answering. If the "
                "user asks for all exceptions, all alarms, current alarms, or a "
                "device abnormal list, call get_device_alarms and summarize real "
                "alarm records. If the user asks about an alarm code, fault reason, "
                "or maintenance method without a device, call search_knowledge. "
                "You are forbidden to generate device status, "
                "temperature, voltage, current, runtime metrics, or alarm information "
                "or alarm data without tool results. Tool calls have priority over final JSON output. "
                "After tool results are returned, generate the final JSON answer. "
                "Final content must be a JSON object "
                "matching AgentDiagnosisDraft with fields: problem_summary, "
                "risk_level, possible_causes, recommended_actions, warnings. "
                "Credibility rules: problem_summary must list only confirmed facts "
                "from tool results such as device status, runtime metrics, alarm "
                "records, and retrieved document sources. possible_causes must be "
                "phrased as possibilities, not confirmed root causes. For every "
                "possible cause, include basis text such as 'Basis: ...' referencing "
                "device data, alarm data, or RAG sources when available. "
                "recommended_actions must be verification methods or next manual "
                "checks, for example checking current trend, load, wiring, cooling, "
                "or controller status. Do not claim a definitive cause until tool "
                "results provide direct proof. "
                "Do not invent device data or sources. Final response rules: "
                "Only output JSON object. No markdown. Do not add explanations "
                "outside JSON. risk_level must be one of: low, medium, high, "
                "critical, unknown."
            ),
        }
    ]
    for message in history_messages:
        if message.role in {"system", "user", "assistant"}:
            messages.append({"role": message.role, "content": message.content})

    if request.device_code:
        user_content = f"设备编号: {request.device_code}\n用户问题: {request.query}"
    else:
        user_content = request.query

    messages.append({"role": "user", "content": user_content})
    return messages


def _route_query_from_request(request: AgentDiagnoseRequest) -> str:
    if request.device_code:
        return f"设备编号: {request.device_code}\n用户问题: {request.query}"

    return request.query


def _is_alarm_overview_route(tool_names: list[str]) -> bool:
    return "get_device_alarms" in tool_names and "search_knowledge" not in tool_names


def _run_alarm_overview_query(
    request: AgentDiagnoseRequest,
    executor: ToolCallExecutor,
) -> AgentRuntimeResult:
    tool_results: list[dict[str, Any]] = []
    alarm_arguments = {
        "device_code": request.device_code,
        "limit": 20,
        "unresolved_only": True,
    }
    alarm_result = executor.execute("get_device_alarms", alarm_arguments)
    tool_results.append(alarm_result)
    agent_trace.record_tool_result(alarm_result)

    device_code = request.device_code or _infer_device_code_from_alarm_result(alarm_result)
    if device_code:
        status_result = executor.execute(
            "get_device_status",
            {
                "device_code": device_code,
            },
        )
        tool_results.append(status_result)
        agent_trace.record_tool_result(status_result)

    return AgentRuntimeResult(
        success=True,
        content=None,
        messages=[],
        tool_results=tool_results,
        error=None,
    )


def _run_final_llm_from_tool_results(
    *,
    request: AgentDiagnoseRequest,
    runtime_result: AgentRuntimeResult,
    llm_provider: ToolCallingProvider,
) -> AgentRuntimeResult:
    messages = _build_final_llm_messages_from_tool_results(request, runtime_result.tool_results)
    try:
        llm_response = llm_provider.complete_with_tools(
            messages=messages,
            tools=[],
            tool_choice="auto",
        )
    except Exception:
        logger.exception("Agent runtime alarm overview final LLM call failed.")
        return AgentRuntimeResult(
            success=False,
            content=None,
            messages=messages,
            tool_results=runtime_result.tool_results,
            error="final_llm_failed",
            fallback_reason="final_llm_failed",
        )

    return AgentRuntimeResult(
        success=True,
        content=llm_response.content or "",
        messages=messages,
        tool_results=runtime_result.tool_results,
        error=None,
    )


def _build_final_llm_messages_from_tool_results(
    request: AgentDiagnoseRequest,
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "You are an enterprise equipment diagnosis agent. Generate the final "
                "structured diagnosis report only from the provided tool results. "
                "Do not invent devices, alarms, metrics, or sources. Output only a "
                "valid JSON object. No markdown. The JSON should contain either "
                "problem_summary/risk_level/possible_causes/recommended_actions/warnings "
                "or summary/risk_level/possible_causes/suggestions/warnings. "
                "problem_summary must contain confirmed facts only. possible_causes "
                "must be written as possible causes and include basis text such as "
                "'Basis: ...'. suggestions/recommended_actions must be verification "
                "methods for manual inspection. Do not state inferred causes as "
                "certain conclusions. "
                "risk_level must be one of: low, medium, high, critical, unknown."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_query": request.query,
                    "device_code": request.device_code,
                    "tool_results": tool_results,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _infer_device_code_from_alarm_result(tool_result: dict[str, Any]) -> str | None:
    result = tool_result.get("result")
    if not isinstance(result, dict):
        return None

    alarms = result.get("alarms")
    if not isinstance(alarms, list):
        return None

    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        device_code = alarm.get("device_id")
        if isinstance(device_code, str) and device_code.strip():
            return device_code.strip().upper()

    return None


def _infer_device_code_from_tool_results(tool_results: list[dict[str, Any]]) -> str | None:
    for tool_result in reversed(tool_results):
        device_code = _infer_device_code_from_alarm_result(tool_result)
        if device_code:
            return device_code

        result = tool_result.get("result")
        if not isinstance(result, dict):
            continue

        device = result.get("device")
        if not isinstance(device, dict):
            continue

        raw_device_code = device.get("device_code")
        if isinstance(raw_device_code, str) and raw_device_code.strip():
            return raw_device_code.strip().upper()

    return None


def _format_alarm_query_term(
    alarm_code: object,
    alarm_name: object,
) -> str:
    code = str(alarm_code).strip().upper() if alarm_code is not None else ""
    name = str(alarm_name).strip() if alarm_name is not None else ""
    return _join_query_parts([code, name])


def _knowledge_terms_from_runtime_tool_results(
    tool_results: list[dict[str, Any]],
) -> tuple[list[str], str | None]:
    alarm_terms: list[str] = []
    device_type: str | None = None

    for tool_result in tool_results:
        if not tool_result.get("success"):
            continue
        payload = tool_result.get("result")
        if not isinstance(payload, dict):
            continue

        if tool_result.get("tool_name") == "get_device_status":
            device = payload.get("device")
            if isinstance(device, dict):
                raw_device_type = device.get("device_type")
                if isinstance(raw_device_type, str) and raw_device_type.strip():
                    device_type = raw_device_type.strip()

            recent_alarms = payload.get("recent_alarms")
            if isinstance(recent_alarms, list):
                for alarm in recent_alarms:
                    if not isinstance(alarm, dict):
                        continue
                    alarm_terms.append(
                        _format_alarm_query_term(
                            alarm.get("alarm_code"),
                            alarm.get("message"),
                        )
                    )

        if tool_result.get("tool_name") == "get_device_alarms":
            alarms = payload.get("alarms")
            if isinstance(alarms, list):
                for alarm in alarms:
                    if not isinstance(alarm, dict):
                        continue
                    alarm_terms.append(
                        _format_alarm_query_term(
                            alarm.get("alarm_code"),
                            alarm.get("alarm_name"),
                        )
                    )

    return _prefer_detailed_alarm_terms(alarm_terms), device_type


def _prefer_detailed_alarm_terms(alarm_terms: list[str]) -> list[str]:
    deduped_terms = _dedupe([term for term in alarm_terms if term])
    detailed_terms: list[str] = []
    for term in deduped_terms:
        if any(
            other != term
            and other.startswith(f"{term} ")
            and re.fullmatch(r"E\d{3,}", term, re.IGNORECASE)
            for other in deduped_terms
        ):
            continue
        detailed_terms.append(term)

    return detailed_terms


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


def _build_query_alarm_mismatch_warnings(
    query: str,
    concerns: set[str],
    alarm_terms: list[str],
    tool_results: list[dict[str, Any]],
) -> list[str]:
    if not concerns:
        return []

    matched_alarm_terms = [
        term for term in alarm_terms if _alarm_term_matches_query_concern(term, concerns)
    ]
    if matched_alarm_terms:
        return []

    concern_labels = _parameter_labels(concerns)
    current_alarm_text = "、".join(alarm_terms) if alarm_terms else "无未解决报警"
    normal_concerns = [
        concern for concern in concerns if _runtime_parameter_is_normal(concern, tool_results)
    ]
    if normal_concerns:
        return [
            (
                f"未发现{_parameter_labels(set(normal_concerns))}异常，请确认描述。"
                f"当前设备真实异常：{current_alarm_text}。"
            )
        ]

    return [
        (
            f"用户关注问题：{concern_labels}。"
            f"当前设备真实异常：{current_alarm_text}。"
        )
    ]


def _detect_intent_mismatch(
    query: str,
    tool_results: list[dict[str, Any]],
) -> dict[str, str] | None:
    concerns = _extract_query_parameter_concerns(query)
    if not concerns:
        return None

    alarm_terms, _device_type = _knowledge_terms_from_runtime_tool_results(tool_results)
    if any(_alarm_term_matches_query_concern(term, concerns) for term in alarm_terms):
        return None

    normal_concerns = [
        concern for concern in concerns if _runtime_parameter_is_normal(concern, tool_results)
    ]
    if not normal_concerns:
        return None

    return {
        "concern": _parameter_labels(set(normal_concerns)),
        "current_alarms": "、".join(alarm_terms) if alarm_terms else "无未解决报警",
    }


def _runtime_parameter_is_normal(
    concern: str,
    tool_results: list[dict[str, Any]],
) -> bool:
    if concern not in RUNTIME_PARAMETER_LIMITS:
        return False

    runtime_data = _latest_runtime_payload_from_tool_results(tool_results)
    if runtime_data is None:
        return False

    value = runtime_data.get(concern)
    if not isinstance(value, int | float):
        return False

    limits = RUNTIME_PARAMETER_LIMITS[concern]
    minimum = limits.get("min")
    maximum = limits.get("max")
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False

    return True


def _latest_runtime_payload_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for tool_result in reversed(tool_results):
        if tool_result.get("tool_name") != "get_device_status" or not tool_result.get("success"):
            continue
        result = tool_result.get("result")
        if not isinstance(result, dict):
            continue
        runtime_data = result.get("latest_runtime_data")
        if isinstance(runtime_data, dict):
            return runtime_data

    return None


def _parameter_labels(parameters: set[str]) -> str:
    return "、".join(
        PARAMETER_LABELS.get(parameter, parameter)
        for parameter in sorted(parameters)
    )


def _join_query_parts(parts: list[str | None]) -> str:
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


def _build_runtime_response_from_draft(
    *,
    draft: AgentDiagnosisDraft,
    tool_state: dict[str, Any],
) -> AgentDiagnoseResponse:
    minimum_risk_level = _calculate_runtime_minimum_risk_level(tool_state)
    risk_level = enforce_minimum_risk_level(draft.risk_level, minimum_risk_level)
    if not _has_tool_evidence(tool_state):
        risk_level = "unknown"

    return AgentDiagnoseResponse(
        problem_summary=draft.problem_summary,
        device=tool_state["device"],
        device_status=tool_state["device_status"],
        recent_alarms=tool_state["recent_alarms"],
        risk_level=risk_level,
        possible_causes=draft.possible_causes,
        recommended_actions=draft.recommended_actions,
        sources=_dedupe(tool_state["sources"]),
        tools_used=_dedupe(tool_state["tools_used"]),
        warnings=_dedupe([*tool_state["warnings"], *draft.warnings]),
        disclaimer=DISCLAIMER,
    )


def _collect_tool_state(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    device_result: DeviceStatusToolResult | None = None
    alarms_result: DeviceAlarmsToolResult | None = None
    knowledge_result: KnowledgeSearchToolResult | None = None
    tools_used: list[str] = []
    sources: list[str] = []
    warnings: list[str] = []
    alarm_overview: list[dict[str, Any]] = []

    for tool_result in tool_results:
        tool_name = tool_result.get("tool_name")
        if not tool_result.get("success"):
            warnings.append(f"Tool failed: {tool_name}")
            continue

        payload = tool_result.get("result") or {}
        if tool_name == "get_device_status":
            try:
                device_result = DeviceStatusToolResult.model_validate(payload)
            except Exception:
                logger.exception("Runtime device tool result validation failed.")
                warnings.append("设备工具结果无法使用。")
                continue
            warnings.extend(device_result.warnings)
            if device_result.ok:
                tools_used.append("get_device_status")
            else:
                warnings.append("设备状态查询工具暂时不可用。")
        elif tool_name == "get_device_alarms":
            try:
                alarms_result = DeviceAlarmsToolResult.model_validate(payload)
            except Exception:
                logger.exception("Runtime alarms tool result validation failed.")
                warnings.append("报警工具结果无法使用。")
                continue
            warnings.extend(alarms_result.warnings)
            if alarms_result.ok:
                tools_used.append("get_device_alarms")
                alarm_overview = [
                    alarm.model_dump(mode="json") for alarm in alarms_result.alarms
                ]
            else:
                warnings.append("报警查询工具暂时不可用。")
        elif tool_name == "search_knowledge":
            try:
                knowledge_result = KnowledgeSearchToolResult.model_validate(payload)
            except Exception:
                logger.exception("Runtime knowledge tool result validation failed.")
                warnings.append("知识库工具结果无法使用。")
                continue
            warnings.extend(knowledge_result.warnings)
            if knowledge_result.ok:
                tools_used.append("search_knowledge")
                sources.extend(result.source for result in knowledge_result.results)
            else:
                warnings.append("知识库检索工具暂时不可用。")

    return {
        "device_result": device_result,
        "alarms_result": alarms_result,
        "knowledge_result": knowledge_result,
        "device": device_result.device if device_result is not None and device_result.ok else None,
        "device_status": (
            device_result.latest_runtime_data
            if device_result is not None and device_result.ok
            else None
        ),
        "recent_alarms": (
            device_result.recent_alarms
            if device_result is not None and device_result.ok
            else []
        ),
        "alarm_overview": alarm_overview,
        "sources": sources,
        "tools_used": tools_used,
        "warnings": warnings,
    }


def _parse_runtime_draft(content: str | None) -> AgentDiagnosisDraft | None:
    return _parse_runtime_draft_with_reason(content).draft


def _parse_runtime_draft_with_reason(
    content: str | None,
) -> RuntimeDraftParseResult:
    if content is None or not content.strip():
        logger.debug("Runtime draft parse failed: empty content.")
        return RuntimeDraftParseResult(
            draft=None,
            fallback_reason="empty_final_content",
        )

    logger.info(
        "Runtime final raw LLM response preview: %s",
        _safe_runtime_response_preview(content),
    )
    json_text = _extract_runtime_json_object(content)
    if json_text is None:
        fallback_reason = (
            "json_decode_failed"
            if content.strip().startswith("{")
            else "json_extract_failed"
        )
        if fallback_reason == "json_extract_failed":
            plain_text_draft = _parse_plain_text_runtime_draft(content)
            if plain_text_draft is not None:
                logger.debug("Runtime draft recovered from non-JSON final content.")
                return RuntimeDraftParseResult(
                    draft=plain_text_draft,
                    fallback_reason=None,
                )

        logger.debug(
            "Runtime draft JSON parse failed: reason=%s",
            fallback_reason,
        )
        return RuntimeDraftParseResult(
            draft=None,
            fallback_reason=fallback_reason,
        )

    logger.debug("Runtime draft JSON parse success.")
    try:
        data = _loads_runtime_json(json_text)
        data = _normalize_runtime_draft_data(data)
    except json.JSONDecodeError as exc:
        logger.debug(
            "Runtime draft JSON parse failed: error_type=%s",
            type(exc).__name__,
        )
        return RuntimeDraftParseResult(
            draft=None,
            fallback_reason="json_decode_failed",
        )

    try:
        return RuntimeDraftParseResult(
            draft=AgentDiagnosisDraft.model_validate(data),
            fallback_reason=None,
        )
    except ValidationError as exc:
        logger.info(
            "Runtime draft validation failed: %s",
            exc,
        )
        missing_fields = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()
            if error.get("type") == "missing"
        ]
        logger.debug(
            "Runtime draft validation failed: error_type=%s missing_fields=%s",
            type(exc).__name__,
            missing_fields,
        )
        return RuntimeDraftParseResult(
            draft=None,
            fallback_reason="schema_validation_failed",
        )
    except Exception as exc:
        logger.debug(
            "Runtime draft validation failed: error_type=%s",
            type(exc).__name__,
        )
        return RuntimeDraftParseResult(
            draft=None,
            fallback_reason="schema_validation_failed",
        )


def _extract_runtime_json_object(content: str) -> str | None:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            parsed, end_index = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return stripped[index : index + end_index]

    return _extract_balanced_runtime_json_object(stripped)


def _extract_balanced_runtime_json_object(content: str) -> str | None:
    start_index = content.find("{")
    if start_index == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for index in range(start_index, len(content)):
        character = content[index]
        if in_string:
            if escape_next:
                escape_next = False
            elif character == "\\":
                escape_next = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return content[start_index : index + 1]

    return None


def _loads_runtime_json(json_text: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        repaired_json_text = _repair_runtime_json_text(json_text)
        if repaired_json_text == json_text:
            raise

    return json.loads(repaired_json_text)


def _repair_runtime_json_text(json_text: str) -> str:
    repaired = json_text.strip()
    repaired = repaired.replace("\ufeff", "")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _parse_plain_text_runtime_draft(content: str) -> AgentDiagnosisDraft | None:
    normalized_text = _normalize_plain_runtime_text(content)
    if not _looks_like_plain_diagnosis(normalized_text):
        return None

    data = {
        "problem_summary": _extract_plain_problem_summary(normalized_text),
        "risk_level": _extract_plain_risk_level(normalized_text),
        "possible_causes": _extract_plain_section_items(
            normalized_text,
            ("possible_causes", "Possible causes", "可能原因", "原因分析", "故障原因"),
        ),
        "recommended_actions": _extract_plain_section_items(
            normalized_text,
            (
                "recommended_actions",
                "Recommended actions",
                "处理建议",
                "建议措施",
                "排查步骤",
                "解决方案",
            ),
        ),
        "warnings": [
            "最终分析结果不是严格结构化 JSON，已按文本摘要进行解析。"
        ],
    }
    try:
        return AgentDiagnosisDraft.model_validate(_normalize_runtime_draft_data(data))
    except Exception:
        logger.debug("Runtime plain text draft recovery failed.", exc_info=True)
        return None


def _normalize_plain_runtime_text(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    return stripped


def _looks_like_plain_diagnosis(content: str) -> bool:
    if len(content.strip()) < 12:
        return False

    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", content))


def _extract_plain_problem_summary(content: str) -> str:
    for label in (
        "problem_summary",
        "Problem summary",
        "问题总结",
        "问题摘要",
        "故障概述",
        "诊断摘要",
        "总结",
    ):
        extracted = _extract_plain_labeled_value(content, label)
        if extracted:
            return extracted

    for line in content.splitlines():
        cleaned = _clean_plain_list_item(line)
        if cleaned:
            return cleaned[:500]

    return content[:500]


def _extract_plain_risk_level(content: str) -> str:
    for label in ("risk_level", "Risk level", "风险等级", "风险级别", "风险"):
        extracted = _extract_plain_labeled_value(content, label)
        if extracted:
            normalized = _normalize_runtime_draft_data({"risk_level": extracted})
            risk_level = normalized.get("risk_level")
            if isinstance(risk_level, str) and risk_level in {
                "unknown",
                "low",
                "medium",
                "high",
                "critical",
            }:
                return risk_level

    normalized = _normalize_runtime_draft_data({"risk_level": content})
    risk_level = normalized.get("risk_level")
    if isinstance(risk_level, str) and risk_level in {
        "unknown",
        "low",
        "medium",
        "high",
        "critical",
    }:
        return risk_level

    return "unknown"


def _extract_plain_labeled_value(content: str, label: str) -> str | None:
    pattern = re.compile(
        rf"^\s*(?:[-*#\d.、\s]*){re.escape(label)}\s*[:：]\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        return _clean_plain_list_item(match.group(1))

    return None


def _extract_plain_section_items(
    content: str,
    labels: tuple[str, ...],
) -> list[str]:
    lines = content.splitlines()
    label_pattern = re.compile(
        rf"^\s*(?:[-*#\d.、\s]*)({'|'.join(re.escape(label) for label in labels)})\s*[:：]?\s*(.*)$",
        re.IGNORECASE,
    )
    next_section_pattern = re.compile(
        r"^\s*(?:[-*#\d.、\s]*)(problem_summary|risk_level|possible_causes|recommended_actions|warnings|问题总结|问题摘要|故障概述|诊断摘要|风险等级|风险级别|可能原因|原因分析|故障原因|处理建议|建议措施|排查步骤|解决方案|注意事项|警告|风险提示)\s*[:：]?\s*",
        re.IGNORECASE,
    )
    items: list[str] = []
    in_section = False
    for line in lines:
        label_match = label_pattern.match(line)
        if label_match:
            in_section = True
            inline_value = _clean_plain_list_item(label_match.group(2))
            if inline_value:
                items.append(inline_value)
            continue

        if in_section and next_section_pattern.match(line):
            break

        if in_section:
            item = _clean_plain_list_item(line)
            if item:
                items.append(item)

    return items[:10]


def _clean_plain_list_item(value: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", value).strip()


def _safe_runtime_response_preview(content: str) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    if len(compact) <= RUNTIME_RESPONSE_LOG_PREVIEW_LIMIT:
        return compact

    return f"{compact[:RUNTIME_RESPONSE_LOG_PREVIEW_LIMIT]}..."


def _normalize_runtime_draft_data(data: Any) -> Any:
    if not isinstance(data, dict):
        return data

    if "problem_summary" not in data and "summary" in data:
        data = {**data, "problem_summary": data.get("summary")}
    if "recommended_actions" not in data and "suggestions" in data:
        data = {**data, "recommended_actions": data.get("suggestions")}

    normalized = {
        key: value
        for key, value in data.items()
        if key in RUNTIME_DRAFT_ALLOWED_FIELDS
    }
    risk_level = normalized.get("risk_level")
    if isinstance(risk_level, str):
        normalized["risk_level"] = RUNTIME_RISK_LEVEL_ALIASES.get(
            risk_level.strip(),
            risk_level,
        )

    normalized.setdefault("possible_causes", [])
    normalized.setdefault("recommended_actions", [])
    normalized.setdefault("warnings", [])

    return normalized


def _build_runtime_fallback_response(
    request: AgentDiagnoseRequest,
    runtime_result: AgentRuntimeResult,
    tool_state: dict[str, Any],
) -> AgentDiagnoseResponse:
    minimum_risk_level = _calculate_runtime_minimum_risk_level(tool_state)
    risk_level = minimum_risk_level if _has_tool_evidence(tool_state) else "unknown"
    warnings = [*tool_state["warnings"]]
    if runtime_result.error == "final_llm_failed" and _has_tool_evidence(tool_state):
        warnings.append(FINAL_LLM_UNAVAILABLE_WARNING)
    else:
        warnings.append(RUNTIME_FALLBACK_WARNING)

    if runtime_result.error and runtime_result.error != "final_llm_failed":
        warnings.append(f"Runtime stopped: {runtime_result.error}")
    if runtime_result.fallback_reason:
        warnings.append(f"Runtime fallback reason: {runtime_result.fallback_reason}")

    return AgentDiagnoseResponse(
        problem_summary=(
            "当前 AI 工具调用诊断暂时不可用，以下结果基于已获得的工具数据生成。"
            if _has_tool_evidence(tool_state)
            else "当前无法完成工具调用诊断，请补充设备编号、报警码或故障现象。"
        ),
        device=tool_state["device"],
        device_status=tool_state["device_status"],
        recent_alarms=tool_state["recent_alarms"],
        risk_level=risk_level,
        possible_causes=[],
        recommended_actions=_fallback_actions(risk_level, request),
        sources=_dedupe(tool_state["sources"]),
        tools_used=_dedupe(tool_state["tools_used"]),
        warnings=_dedupe(warnings),
        disclaimer=DISCLAIMER,
    )


def _fallback_actions(
    risk_level: str,
    request: AgentDiagnoseRequest,
) -> list[str]:
    if risk_level in {"high", "critical"}:
        return [
            "停止高负载运行。",
            "检查设备是否需要安全停机。",
            "检查散热、供电、传感器和报警记录。",
            "联系专业维护人员进行现场确认。",
        ]

    return [
        "提供设备编号、报警码和最新运行数据。",
        "结合设备状态和知识库来源进行现场排查。",
        "由现场人员进行基础安全检查。",
        f"继续补充问题细节：{request.query}",
    ]


def _has_tool_evidence(tool_state: dict[str, Any]) -> bool:
    device_result = tool_state["device_result"]
    alarms_result = tool_state.get("alarms_result")
    knowledge_result = tool_state["knowledge_result"]
    return (
        device_result is not None
        and device_result.ok
        and (
            device_result.device is not None
            or device_result.latest_runtime_data is not None
            or bool(device_result.recent_alarms)
        )
    ) or (
        alarms_result is not None
        and alarms_result.ok
        and bool(alarms_result.alarms)
    ) or (
        knowledge_result is not None
        and knowledge_result.ok
        and bool(knowledge_result.results)
    )


def _calculate_runtime_minimum_risk_level(tool_state: dict[str, Any]) -> str:
    device_minimum = calculate_minimum_risk_level(tool_state["device_result"])
    alarms_result = tool_state.get("alarms_result")
    if alarms_result is None or not alarms_result.ok:
        return device_minimum

    levels = [alarm.level.lower() for alarm in alarms_result.alarms]
    if "critical" in levels:
        return "critical"
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    if "low" in levels:
        return "low"
    return device_minimum


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
