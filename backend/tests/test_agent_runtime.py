import json
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent.runtime import (  # noqa: E402
    FINAL_LLM_UNAVAILABLE_WARNING,
    MAX_TOOL_ITERATIONS,
    AgentRuntime,
    AgentRuntimeLLMResponse,
    AgentRuntimeResult,
    AgentRuntimeToolCall,
    _build_runtime_fallback_response,
    _build_runtime_messages,
    _collect_tool_state,
    _normalize_runtime_draft_data,
    _parse_runtime_draft,
    _parse_runtime_draft_with_reason,
)
from app.agent.tool_registry import list_agent_tools  # noqa: E402
from app.llm.base import LLMMessage  # noqa: E402
from app.schemas.agent import AgentDiagnoseRequest  # noqa: E402


def test_runtime_executes_tool_call_and_returns_final_answer() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="search_knowledge",
                        arguments={"query": "E203报警", "top_k": 3},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="E203 should be handled by checking controller wiring."),
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "search_knowledge",
            "success": True,
            "result": {"ok": True, "results": [{"source": "e203.md#chunk-0"}]},
            "error": None,
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run([LLMMessage(role="user", content="E203报警怎么办？")])

    assert result.success is True
    assert result.content == "E203 should be handled by checking controller wiring."
    assert result.error is None
    assert executor.calls == [("search_knowledge", {"query": "E203报警", "top_k": 3})]
    assert provider.calls[0]["tools"][0]["function"]["name"] == "get_device_status"
    assert provider.calls[0]["tools"][1]["function"]["name"] == "search_knowledge"
    assert provider.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "search_knowledge"},
    }


def test_runtime_passes_tool_result_to_next_llm_round() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Final diagnosis."),
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "get_device_status",
            "success": True,
            "result": {"ok": True, "device_exists": True},
            "error": None,
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run([{"role": "user", "content": "查询DEV-001状态"}])

    assert result.success is True
    second_round_messages = provider.calls[1]["messages"]
    tool_message = second_round_messages[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "get_device_status"
    assert json.loads(tool_message["content"]) == {
        "tool_name": "get_device_status",
        "success": True,
        "result": {"ok": True, "device_exists": True},
        "error": None,
    }


def test_runtime_stops_after_max_tool_iterations() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id=f"call_{index}",
                        name="search_knowledge",
                        arguments={"query": "E203"},
                    )
                ]
            )
            for index in range(MAX_TOOL_ITERATIONS + 1)
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "search_knowledge",
            "success": True,
            "result": {"ok": True},
            "error": None,
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run([LLMMessage(role="user", content="E203")])

    assert result.success is False
    assert result.error == "max_tool_iterations_exceeded"
    assert result.fallback_reason == "max_tool_iterations_exceeded"
    assert len(provider.calls) == MAX_TOOL_ITERATIONS
    assert len(executor.calls) == MAX_TOOL_ITERATIONS


def test_runtime_handles_tool_executor_exception_safely() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="search_knowledge",
                        arguments={"query": "E203"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Final answer after failed tool."),
        ]
    )
    runtime = AgentRuntime(provider, RaisingToolExecutor())  # type: ignore[arg-type]

    result = runtime.run([LLMMessage(role="user", content="E203")])

    assert result.success is True
    assert result.tool_results == [
        {
            "tool_name": "search_knowledge",
            "success": False,
            "result": {},
            "error": "tool_execution_failed",
        }
    ]
    assert "secret traceback" not in json.dumps(result.tool_results)


def test_runtime_handles_llm_failure_safely() -> None:
    provider = FailingProvider()
    executor = FakeToolExecutor({})
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run([LLMMessage(role="user", content="E203")])

    assert result.success is False
    assert result.error == "llm_failed"
    assert result.content == "Unable to complete the request because the LLM is unavailable."
    assert "provider secret" not in result.content


def test_runtime_preserves_tool_results_when_final_llm_fails() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            RuntimeFail("final provider failure"),
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "get_device_status",
            "success": True,
            "result": {
                "ok": True,
                "device_exists": True,
                "device": {
                    "id": 1,
                    "device_code": "DEV-001",
                    "name": "Demo Device",
                    "device_type": "pump",
                    "location": "Workshop A",
                    "is_online": True,
                    "created_at": "2026-07-16T16:02:42.493277",
                },
                "latest_runtime_data": {
                    "id": 20,
                    "device_id": 1,
                    "temperature": 47.5,
                    "voltage": 228.78,
                    "current": 4.44,
                    "vibration": 0.13,
                    "status": "normal",
                    "recorded_at": "2026-07-16T16:01:42.502206",
                    "created_at": "2026-07-16T16:02:42.506751",
                },
                "recent_alarms": [],
                "warnings": [],
            },
            "error": None,
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run([LLMMessage(role="user", content="查询DEV-001当前状态")])
    tool_state = _collect_tool_state(result.tool_results)
    response = _build_runtime_fallback_response(
        AgentDiagnoseRequest(query="查询DEV-001当前状态"),
        result,
        tool_state,
    )

    assert result.success is False
    assert result.error == "final_llm_failed"
    assert result.fallback_reason == "final_llm_failed"
    assert len(result.tool_results) == 1
    assert response.device.device_code == "DEV-001"
    assert response.device_status.temperature == 47.5
    assert response.tools_used == ["get_device_status"]
    assert FINAL_LLM_UNAVAILABLE_WARNING in response.warnings
    assert "Runtime fallback reason: final_llm_failed" in response.warnings
    assert "Runtime stopped: llm_failed" not in response.warnings


def test_runtime_retries_final_llm_once_and_returns_success() -> None:
    sleeps: list[float] = []
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            RuntimeFail("transient final failure"),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    {
                        "problem_summary": "Recovered final diagnosis.",
                        "risk_level": "medium",
                    }
                )
            ),
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "get_device_status",
            "success": True,
            "result": {"ok": True, "device_exists": True},
            "error": None,
        }
    )
    runtime = AgentRuntime(
        provider,
        executor,  # type: ignore[arg-type]
        sleep_func=sleeps.append,
    )

    result = runtime.run([LLMMessage(role="user", content="查询DEV-001当前状态")])

    assert result.success is True
    assert result.error is None
    assert result.fallback_reason is None
    assert json.loads(result.content)["problem_summary"] == "Recovered final diagnosis."
    assert len(result.tool_results) == 1
    assert len(provider.calls) == 3
    assert sleeps == [0.5]


def test_runtime_final_llm_retry_failure_still_falls_back() -> None:
    sleeps: list[float] = []
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            RuntimeFail("first final failure"),
            RuntimeFail("second final failure"),
        ]
    )
    executor = FakeToolExecutor(
        {
            "tool_name": "get_device_status",
            "success": True,
            "result": {"ok": True, "device_exists": True},
            "error": None,
        }
    )
    runtime = AgentRuntime(
        provider,
        executor,  # type: ignore[arg-type]
        sleep_func=sleeps.append,
    )

    result = runtime.run([LLMMessage(role="user", content="查询DEV-001当前状态")])

    assert result.success is False
    assert result.error == "final_llm_failed"
    assert result.fallback_reason == "final_llm_failed"
    assert len(result.tool_results) == 1
    assert len(provider.calls) == 3
    assert sleeps == [0.5]


def test_runtime_accepts_explicit_tool_registry() -> None:
    provider = FakeToolCallingProvider([AgentRuntimeLLMResponse(content="Done.")])
    executor = FakeToolExecutor({})
    runtime = AgentRuntime(
        provider,
        executor,  # type: ignore[arg-type]
        tool_registry=[list_agent_tools()[1]],
    )

    runtime.run([LLMMessage(role="user", content="E203")])

    assert [tool["function"]["name"] for tool in provider.calls[0]["tools"]] == [
        "search_knowledge"
    ]


def test_runtime_forces_device_tool_choice_for_device_status_query() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = FakeToolExecutor(
        {"tool_name": "get_device_status", "success": True, "result": {}, "error": None}
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="查询DEV-001当前状态")])

    assert provider.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_device_status"},
    }
    assert provider.calls[1]["tool_choice"] == "auto"


def test_runtime_forces_knowledge_tool_choice_for_alarm_reason_query() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="search_knowledge",
                        arguments={"query": "E203报警是什么原因？"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = FakeToolExecutor(
        {"tool_name": "search_knowledge", "success": True, "result": {}, "error": None}
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="E203报警是什么原因？")])

    assert provider.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "search_knowledge"},
    }


def test_runtime_forces_two_tool_choices_for_device_alarm_query() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_2",
                        name="search_knowledge",
                        arguments={"query": "E203"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = FakeToolExecutor(
        {"tool_name": "tool", "success": True, "result": {}, "error": None}
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="DEV-001 E203报警")])

    assert provider.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_device_status"},
    }
    assert provider.calls[1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "search_knowledge"},
    }
    assert provider.calls[2]["tool_choice"] == "auto"


def test_runtime_keeps_auto_tool_choice_for_general_query() -> None:
    provider = FakeToolCallingProvider([AgentRuntimeLLMResponse(content="Done.")])
    executor = FakeToolExecutor({})
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="你好")])

    assert provider.calls[0]["tool_choice"] == "auto"


def test_runtime_system_prompt_contains_tool_selection_rules() -> None:
    messages = _build_runtime_messages(
        AgentDiagnoseRequest(query="查询DEV-001当前状态"),
        [],
    )

    system_prompt = messages[0]["content"]
    assert "Mandatory Tool Usage Rules" in system_prompt
    assert "DEV-xxx" in system_prompt
    assert "状态" in system_prompt
    assert "当前" in system_prompt
    assert "运行" in system_prompt
    assert "运行情况" in system_prompt
    assert "在线" in system_prompt
    assert "设备信息" in system_prompt
    assert "MUST call get_device_status" in system_prompt
    assert "alarm code" in system_prompt
    assert "MUST call get_device_status and search_knowledge" in system_prompt
    assert "fault reason" in system_prompt
    assert "maintenance method" in system_prompt
    assert "call search_knowledge" in system_prompt
    assert "forbidden to generate device status" in system_prompt
    assert "temperature" in system_prompt
    assert "voltage" in system_prompt
    assert "current" in system_prompt
    assert "alarm data" in system_prompt
    assert "Tool calls have priority over final JSON output" in system_prompt
    assert "After tool results are returned" in system_prompt
    assert "final JSON answer" in system_prompt
    assert "Final response rules" in system_prompt
    assert "Only output JSON object" in system_prompt
    assert "No markdown" in system_prompt
    assert "Do not add explanations outside JSON" in system_prompt
    assert "risk_level must be one of: low, medium, high, critical, unknown" in (
        system_prompt
    )


def test_runtime_normalizes_chinese_risk_level_before_validation() -> None:
    normalized = _normalize_runtime_draft_data(
        {
            "problem_summary": "Device status summary.",
            "risk_level": "中风险",
        }
    )

    assert normalized["risk_level"] == "medium"


def test_runtime_parse_draft_accepts_chinese_risk_level_and_missing_optional_fields() -> None:
    draft = _parse_runtime_draft(
        json.dumps(
            {
                "problem_summary": "Device status summary.",
                "risk_level": "中风险",
            },
            ensure_ascii=False,
        )
    )

    assert draft is not None
    assert draft.risk_level == "medium"
    assert draft.possible_causes == []
    assert draft.recommended_actions == []
    assert draft.warnings == []


def test_runtime_parse_draft_accepts_markdown_json_block() -> None:
    draft = _parse_runtime_draft(
        """```json
{
  "problem_summary": "Device status summary.",
  "risk_level": "high",
  "possible_causes": ["Cooling issue"],
  "recommended_actions": ["Inspect fan"],
  "warnings": []
}
```"""
    )

    assert draft is not None
    assert draft.risk_level == "high"
    assert draft.possible_causes == ["Cooling issue"]
    assert draft.recommended_actions == ["Inspect fan"]


def test_runtime_parse_draft_extracts_json_with_surrounding_text() -> None:
    draft = _parse_runtime_draft(
        """
Here is the diagnosis:
{
  "problem_summary": "Device status summary.",
  "risk_level": "low"
}
Please review it.
"""
    )

    assert draft is not None
    assert draft.problem_summary == "Device status summary."
    assert draft.risk_level == "low"
    assert draft.possible_causes == []
    assert draft.recommended_actions == []
    assert draft.warnings == []


def test_runtime_parse_draft_logs_missing_required_fields(caplog) -> None:
    caplog.set_level("DEBUG")

    draft = _parse_runtime_draft('{"risk_level": "low"}')

    assert draft is None
    assert "Runtime draft validation failed" in caplog.text
    assert "problem_summary" in caplog.text


def test_runtime_parse_draft_reports_empty_final_content() -> None:
    result = _parse_runtime_draft_with_reason("   ")

    assert result.draft is None
    assert result.fallback_reason == "empty_final_content"


def test_runtime_parse_draft_reports_json_extract_failed() -> None:
    result = _parse_runtime_draft_with_reason("No JSON object in this answer.")

    assert result.draft is None
    assert result.fallback_reason == "json_extract_failed"


def test_runtime_parse_draft_reports_json_decode_failed() -> None:
    result = _parse_runtime_draft_with_reason('{"problem_summary": "broken"')

    assert result.draft is None
    assert result.fallback_reason == "json_decode_failed"


def test_runtime_parse_draft_reports_schema_validation_failed() -> None:
    result = _parse_runtime_draft_with_reason('{"risk_level": "low"}')

    assert result.draft is None
    assert result.fallback_reason == "schema_validation_failed"


def test_runtime_fallback_response_includes_parse_failure_reason() -> None:
    runtime_result = AgentRuntimeResult(
        success=True,
        content="No JSON object in this answer.",
        messages=[],
        tool_results=[],
        error=None,
        fallback_reason="json_extract_failed",
    )
    response = _build_runtime_fallback_response(
        AgentDiagnoseRequest(query="hello"),
        runtime_result,
        empty_tool_state(),
    )

    assert "Runtime fallback reason: json_extract_failed" in response.warnings


def test_runtime_parse_draft_drops_extra_fields_before_validation() -> None:
    draft = _parse_runtime_draft(
        json.dumps(
            {
                "problem_summary": "Device status summary.",
                "risk_level": "medium",
                "possible_causes": [],
                "recommended_actions": [],
                "warnings": [],
                "device": {"device_code": "DEV-001"},
                "sources": ["manual.md#chunk-0"],
                "tools_used": ["get_device_status"],
                "disclaimer": "Program-owned field.",
            },
            ensure_ascii=False,
        )
    )

    assert draft is not None
    assert draft.problem_summary == "Device status summary."
    assert draft.risk_level == "medium"
    assert not hasattr(draft, "device")
    assert not hasattr(draft, "sources")
    assert not hasattr(draft, "tools_used")
    assert not hasattr(draft, "disclaimer")


def test_runtime_normalizes_common_chinese_risk_level_aliases() -> None:
    expected = {
        "低": "low",
        "中": "medium",
        "一般": "medium",
        "较高": "high",
        "严重": "critical",
        "危险": "critical",
    }

    for raw_level, normalized_level in expected.items():
        normalized = _normalize_runtime_draft_data(
            {
                "problem_summary": "Device status summary.",
                "risk_level": raw_level,
            }
        )

        assert normalized["risk_level"] == normalized_level


def empty_tool_state() -> dict[str, Any]:
    return {
        "device_result": None,
        "knowledge_result": None,
        "device": None,
        "device_status": None,
        "recent_alarms": [],
        "sources": [],
        "tools_used": [],
        "warnings": [],
    }


class FakeToolCallingProvider:
    def __init__(self, responses: list[AgentRuntimeLLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> AgentRuntimeLLMResponse:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeToolExecutor:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return self.result


class RaisingToolExecutor:
    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError("secret traceback")


class FailingProvider:
    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> AgentRuntimeLLMResponse:
        raise RuntimeError("provider secret")


class RuntimeFail(Exception):
    pass
