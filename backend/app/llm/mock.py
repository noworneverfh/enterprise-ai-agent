import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    StructuredModel,
)


class MockLLMProvider:
    """Network-free LLM provider for deterministic tests."""

    def __init__(
        self,
        response: BaseModel | dict | None = None,
        error: LLMProviderError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[list[LLMMessage] | list[dict[str, Any]]] = []

    def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        self.calls.append(messages)

        if self.error is not None:
            raise self.error

        try:
            if isinstance(self.response, response_model):
                return self.response

            return response_model.model_validate(self.response)
        except ValidationError as exc:
            raise LLMStructuredOutputError("LLM output failed schema validation.") from exc

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> Any:
        """Return deterministic tool calls for local runtime demos and tests."""

        from app.agent.runtime import AgentRuntimeLLMResponse, AgentRuntimeToolCall
        from app.agent.tool_choice_router import route_tool_choices

        self.calls.append(messages)

        if self.error is not None:
            raise self.error

        if not tools:
            return AgentRuntimeLLMResponse(content=self._response_json(), tool_calls=[])

        available_tool_names = {
            str(tool.get("function", {}).get("name"))
            for tool in tools
            if isinstance(tool.get("function"), dict)
        }
        latest_user_query = self._latest_user_query(messages)
        tool_names = self._forced_tool_names(tool_choice)
        if not tool_names:
            tool_names = route_tool_choices(latest_user_query).tool_names
        if not tool_names:
            tool_names = self._fallback_tool_names(latest_user_query, available_tool_names)

        selected_tool_names = [
            name for name in tool_names if name in available_tool_names
        ]
        if not selected_tool_names:
            return AgentRuntimeLLMResponse(content=self._response_json(), tool_calls=[])

        return AgentRuntimeLLMResponse(
            content=None,
            tool_calls=[
                AgentRuntimeToolCall(
                    id=f"mock-call-{index}",
                    name=tool_name,
                    arguments=self._tool_arguments(tool_name, latest_user_query),
                )
                for index, tool_name in enumerate(selected_tool_names, start=1)
            ],
        )

    def _response_json(self) -> str:
        if isinstance(self.response, BaseModel):
            return self.response.model_dump_json()

        return json.dumps(self.response or _default_tool_response(), ensure_ascii=False)

    def _forced_tool_names(self, tool_choice: str | dict[str, Any]) -> list[str]:
        if not isinstance(tool_choice, dict):
            return []

        function = tool_choice.get("function")
        if not isinstance(function, dict):
            return []

        name = function.get("name")
        return [str(name)] if name else []

    def _latest_user_query(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "")

        return ""

    def _tool_arguments(self, tool_name: str, query: str) -> dict[str, Any]:
        device_code = _extract_device_code(query)
        if tool_name == "get_device_status":
            return {"device_code": device_code or ""}

        if tool_name == "get_device_alarms":
            return {
                "device_code": device_code,
                "limit": 20,
                "unresolved_only": True,
            }

        if tool_name == "search_knowledge":
            return {"query": _extract_user_question(query), "top_k": 5}

        return {}

    def _fallback_tool_names(
        self,
        query: str,
        available_tool_names: set[str],
    ) -> list[str]:
        if _extract_device_code(query):
            preferred = [
                "get_device_status",
                "get_device_alarms",
                "search_knowledge",
            ]
            return [name for name in preferred if name in available_tool_names]

        if re.search(r"\bE\d{3,}\b", query, re.IGNORECASE):
            preferred = ["get_device_alarms", "search_knowledge"]
            return [name for name in preferred if name in available_tool_names]

        return []


def _extract_device_code(query: str) -> str | None:
    match = re.search(r"\bDEV-\d+\b", query, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _extract_user_question(query: str) -> str:
    for line in query.splitlines():
        stripped = line.strip()
        if stripped.startswith("用户问题:"):
            return stripped.removeprefix("用户问题:").strip()

    return query.strip()


def _default_tool_response() -> dict[str, object]:
    return {
        "problem_summary": "已根据工具返回的设备状态、报警记录和知识库依据生成辅助诊断摘要。",
        "risk_level": "unknown",
        "possible_causes": [],
        "recommended_actions": [
            "请结合设备数据和维修资料进行现场检查。"
        ],
        "warnings": ["当前使用 Mock LLM Provider，结果仅用于本地测试。"],
    }
