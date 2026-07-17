import json
import logging
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.tool_choice_router import build_openai_tool_choice, route_tool_choices
from app.agent.tool_executor import ToolCallExecutor
from app.agent.tool_registry import AgentToolDefinition, list_agent_tools
from app.agent.workflow import DISCLAIMER, calculate_minimum_risk_level
from app.conversation import service as conversation_service
from app.conversation.models import Conversation, Message
from app.llm.base import LLMMessage
from app.schemas.agent import (
    AgentDiagnoseRequest,
    AgentDiagnoseResponse,
    AgentDiagnosisDraft,
    DeviceStatusToolResult,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolRuntimeData,
    enforce_minimum_risk_level,
)


MAX_TOOL_ITERATIONS = 5
logger = logging.getLogger(__name__)
RUNTIME_FALLBACK_WARNING = "Agent runtime unavailable; returned deterministic fallback."
FINAL_LLM_UNAVAILABLE_WARNING = (
    "Final LLM reasoning unavailable; response generated from tool results."
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
        forced_tool_index = 0

        for _iteration in range(self.max_tool_iterations):
            forced_tool_name = (
                forced_tool_names[forced_tool_index]
                if forced_tool_index < len(forced_tool_names)
                else None
            )
            tool_choice = build_openai_tool_choice(forced_tool_name)
            try:
                response = self.llm_provider.complete_with_tools(
                    messages=runtime_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            except Exception:
                if self._is_final_response_stage(
                    tool_results,
                    forced_tool_names,
                    forced_tool_index,
                ):
                    try:
                        logger.exception(
                            "Agent runtime final LLM call failed; retrying once."
                        )
                        self._sleep(0.5)
                        response = self.llm_provider.complete_with_tools(
                            messages=runtime_messages,
                            tools=tools,
                            tool_choice=tool_choice,
                        )
                    except Exception:
                        logger.exception("Agent runtime final LLM retry failed.")
                        return AgentRuntimeResult(
                            success=False,
                            content=(
                                "Unable to complete the request because the LLM "
                                "is unavailable."
                            ),
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
                        content=(
                            "Unable to complete the request because the LLM is "
                            "unavailable."
                        ),
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
                tool_result = self._execute_tool_call(tool_call)
                tool_results.append(tool_result)
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
    ) -> dict[str, Any]:
        try:
            return self.tool_executor.execute(tool_call.name, tool_call.arguments)
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

    def _latest_user_query(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                return content if isinstance(content, str) else ""

        return ""

    def _is_final_response_stage(
        self,
        tool_results: list[dict[str, Any]],
        forced_tool_names: list[str],
        forced_tool_index: int,
    ) -> bool:
        return bool(tool_results) and forced_tool_index >= len(forced_tool_names)


def run_agent_runtime_diagnosis(
    db: Session,
    request: AgentDiagnoseRequest,
    llm_provider: ToolCallingProvider,
) -> AgentDiagnoseResponse:
    """Run the experimental tool-calling runtime and assemble a diagnosis response."""

    conversation = _get_request_conversation(db, request)
    history_messages = _get_request_history(db, request, conversation)
    _save_user_message(db, conversation, request)

    runtime = AgentRuntime(
        llm_provider=llm_provider,
        tool_executor=ToolCallExecutor(db),
    )
    runtime_result = runtime.run(_build_runtime_messages(request, history_messages))
    tool_state = _collect_tool_state(runtime_result.tool_results)

    if not runtime_result.success:
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
        response = _build_runtime_fallback_response(request, runtime_result, tool_state)
        _save_assistant_message(db, conversation, response)
        return response
    draft = parse_result.draft

    minimum_risk_level = calculate_minimum_risk_level(tool_state["device_result"])
    risk_level = enforce_minimum_risk_level(draft.risk_level, minimum_risk_level)
    if not _has_tool_evidence(tool_state):
        risk_level = "unknown"

    response = AgentDiagnoseResponse(
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
                "both DEV-xxx and an alarm code, you MUST call get_device_status "
                "and search_knowledge before answering. If the user asks about an "
                "alarm code, fault reason, or maintenance method without a device, "
                "call search_knowledge. You are forbidden to generate device status, "
                "temperature, voltage, current, runtime metrics, or alarm information "
                "or alarm data without tool results. Tool calls have priority over final JSON output. "
                "After tool results are returned, generate the final JSON answer. "
                "Final content must be a JSON object "
                "matching AgentDiagnosisDraft with fields: problem_summary, "
                "risk_level, possible_causes, recommended_actions, warnings. "
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

    messages.append({"role": "user", "content": request.query})
    return messages


def _collect_tool_state(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    device_result: DeviceStatusToolResult | None = None
    knowledge_result: KnowledgeSearchToolResult | None = None
    tools_used: list[str] = []
    sources: list[str] = []
    warnings: list[str] = []

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
                warnings.append("Device tool result could not be used.")
                continue
            warnings.extend(device_result.warnings)
            if device_result.ok:
                tools_used.append("get_device_status")
            else:
                warnings.append("Device status tool unavailable.")
        elif tool_name == "search_knowledge":
            try:
                knowledge_result = KnowledgeSearchToolResult.model_validate(payload)
            except Exception:
                logger.exception("Runtime knowledge tool result validation failed.")
                warnings.append("Knowledge tool result could not be used.")
                continue
            warnings.extend(knowledge_result.warnings)
            if knowledge_result.ok:
                tools_used.append("search_knowledge")
                sources.extend(result.source for result in knowledge_result.results)
            else:
                warnings.append("Knowledge search tool unavailable.")

    return {
        "device_result": device_result,
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

    json_text = _extract_runtime_json_object(content)
    if json_text is None:
        fallback_reason = (
            "json_decode_failed"
            if content.strip().startswith("{")
            else "json_extract_failed"
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
        data = json.loads(json_text)
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

    return None


def _normalize_runtime_draft_data(data: Any) -> Any:
    if not isinstance(data, dict):
        return data

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
    minimum_risk_level = calculate_minimum_risk_level(tool_state["device_result"])
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
        knowledge_result is not None
        and knowledge_result.ok
        and bool(knowledge_result.results)
    )


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
