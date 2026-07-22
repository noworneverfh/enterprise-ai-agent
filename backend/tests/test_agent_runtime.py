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
    run_agent_runtime_diagnosis,
)
from app.agent.trace import get_latest_agent_trace, start_agent_trace  # noqa: E402
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
    assert [tool["function"]["name"] for tool in provider.calls[0]["tools"]] == [
        "search_knowledge"
    ]
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
    assert provider.calls[0]["tools"]
    assert provider.calls[1]["tools"] == []
    assert provider.calls[1]["tool_choice"] == "auto"
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
    assert result.content == "智能分析服务暂时不可用，无法完成本次推理。"
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
    assert provider.calls[1]["tools"] == []
    assert provider.calls[2]["tools"] == []
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
    assert provider.calls[1]["tools"] == []
    assert provider.calls[2]["tools"] == []
    assert sleeps == [0.5]


def test_runtime_accepts_explicit_tool_registry() -> None:
    provider = FakeToolCallingProvider([AgentRuntimeLLMResponse(content="Done.")])
    executor = FakeToolExecutor({})
    runtime = AgentRuntime(
        provider,
        executor,  # type: ignore[arg-type]
            tool_registry=[list_agent_tools()[2]],
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
    assert provider.calls[0]["tools"]
    assert provider.calls[1]["tools"] == []
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

    assert provider.calls[0]["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in provider.calls[0]["tools"]] == [
        "get_device_alarms",
        "search_knowledge",
    ]


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
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = FakeToolExecutor(
        {"tool_name": "tool", "success": True, "result": {}, "error": None}
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="DEV-001 E203报警")])

    assert [
        tool["function"]["name"] for tool in provider.calls[0]["tools"]
    ] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert provider.calls[0]["tool_choice"] == "auto"
    assert provider.calls[1]["tools"] == []
    assert provider.calls[1]["tool_choice"] == "auto"


def test_runtime_expresses_multiple_tools_with_auto_tool_choice() -> None:
    provider = FakeToolCallingProvider([AgentRuntimeLLMResponse(content="Done.")])
    executor = FakeToolExecutor({})
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-001\n用户问题: E203报警如何处理",
            )
        ]
    )

    assert [
        tool["function"]["name"] for tool in provider.calls[0]["tools"]
    ] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert provider.calls[0]["tool_choice"] == "auto"


def test_runtime_completes_missing_forced_tool_before_final_answer() -> None:
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
    executor = MappingToolExecutor(
        {
            "get_device_status": {
                "tool_name": "get_device_status",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "device_exists": True,
                    "device": None,
                    "latest_runtime_data": None,
                    "recent_alarms": [],
                    "warnings": [],
                },
                "error": None,
            },
            "search_knowledge": {
                "tool_name": "search_knowledge",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "results": [
                        {
                            "chunk_id": 2,
                            "document_id": 2,
                            "filename": "e203_controller_manual.md",
                            "chunk_index": 0,
                            "content": "E203 handling guide.",
                            "source": "e203_controller_manual.md#chunk-0",
                            "distance": 0.2,
                        }
                    ],
                    "warnings": [],
                },
                "error": None,
            },
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-001\n用户问题: E203报警如何处理",
            )
        ]
    )
    tool_state = _collect_tool_state(result.tool_results)

    assert result.success is True
    assert executor.calls == [
        ("get_device_status", {"device_code": "DEV-001"}),
        ("get_device_alarms", {"device_code": "DEV-001", "limit": 20, "unresolved_only": True}),
        (
            "search_knowledge",
            {
                "query": (
                    "E203 电机运行异常 E203报警如何处理 "
                    "maintenance handling steps"
                ),
                "top_k": 5,
            },
        ),
    ]
    assert tool_state["tools_used"] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert tool_state["sources"] == ["e203_controller_manual.md#chunk-0"]
    second_round_messages = provider.calls[1]["messages"]
    assert [
        message.get("name")
        for message in second_round_messages
        if message.get("role") == "tool"
    ] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert provider.calls[1]["tools"] == []


def test_runtime_enriches_single_device_temperature_query_with_alarm_context() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-003"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = MappingToolExecutor(
        {
            "get_device_status": _device_status_tool_result(
                device_code="DEV-003",
                device_type="sensor",
                alarm_code="E101",
                alarm_message="温度异常",
            ),
            "get_device_alarms": _device_alarms_tool_result(
                device_code="DEV-003",
                alarm_code="E101",
                alarm_name="温度异常",
            ),
            "search_knowledge": _knowledge_tool_result(
                source="e101_maintenance_manual.md#chunk-0",
            ),
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-003\n用户问题: 分析设备温度异常原因",
            )
        ]
    )
    tool_state = _collect_tool_state(result.tool_results)
    search_call = executor.calls[-1]

    assert search_call[0] == "search_knowledge"
    assert search_call[1]["query"] == (
        "E101 温度异常 分析设备温度异常原因 sensor maintenance handling steps"
    )
    assert tool_state["sources"] == ["e101_maintenance_manual.md#chunk-0"]
    assert tool_state["tools_used"] == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_runtime_keeps_warning_when_enriched_single_device_query_has_no_knowledge() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-003"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content="Done."),
        ]
    )
    executor = MappingToolExecutor(
        {
            "get_device_status": _device_status_tool_result(
                device_code="DEV-003",
                device_type="sensor",
                alarm_code="E999",
                alarm_message="未知异常",
            ),
            "get_device_alarms": _device_alarms_tool_result(
                device_code="DEV-003",
                alarm_code="E999",
                alarm_name="未知异常",
            ),
            "search_knowledge": {
                "tool_name": "search_knowledge",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "results": [],
                    "warnings": ["No knowledge results found."],
                },
                "error": None,
            },
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-003\n用户问题: 分析设备未知异常原因",
            )
        ]
    )
    tool_state = _collect_tool_state(result.tool_results)

    assert executor.calls[-1] == (
        "search_knowledge",
        {
            "query": "E999 未知异常 分析设备未知异常原因 sensor maintenance handling steps",
            "top_k": 5,
        },
    )
    assert tool_state["sources"] == []
    assert "No knowledge results found." in tool_state["warnings"]


def test_runtime_does_not_use_unmatched_temperature_alarm_for_normal_vibration_query() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-003"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    {
                        "problem_summary": "Temperature diagnosis should not be used.",
                        "risk_level": "medium",
                        "possible_causes": ["E101 temperature anomaly."],
                        "recommended_actions": ["Inspect temperature sensor."],
                    }
                )
            ),
        ]
    )
    executor = MappingToolExecutor(
        {
            "get_device_status": _device_status_tool_result(
                device_code="DEV-003",
                device_type="sensor",
                alarm_code="E101",
                alarm_message="温度异常",
            ),
            "get_device_alarms": _device_alarms_tool_result(
                device_code="DEV-003",
                alarm_code="E101",
                alarm_name="温度异常",
            ),
            "search_knowledge": {
                "tool_name": "search_knowledge",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "results": [],
                    "warnings": ["No knowledge results found."],
                },
                "error": None,
            },
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-003\n用户问题: 分析设备振动异常原因",
            )
        ]
    )
    tool_state = _collect_tool_state(result.tool_results)
    search_call = executor.calls[-1]

    assert search_call == (
        "search_knowledge",
        {"query": "分析设备振动异常原因", "top_k": 5},
    )
    assert len(provider.calls) == 1
    assert "当前状态：未检测到振动异常" in result.content
    assert "E101 temperature anomaly" not in result.content
    assert tool_state["sources"] == []
    assert "未发现振动异常，请确认描述。当前设备真实异常：E101 温度异常。" in (
        tool_state["warnings"]
    )


def test_runtime_allows_vibration_diagnosis_when_vibration_exceeds_limit() -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-003"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    {
                        "problem_summary": "振动参数已超过安全阈值，需要继续诊断。",
                        "risk_level": "medium",
                        "possible_causes": ["可能存在机械松动或轴承磨损。"],
                        "recommended_actions": ["检查振动趋势和轴承状态。"],
                    },
                    ensure_ascii=False,
                )
            ),
        ]
    )
    executor = MappingToolExecutor(
        {
            "get_device_status": _device_status_tool_result(
                device_code="DEV-005",
                device_type="motor",
                alarm_code="E201",
                alarm_message="振动异常",
                vibration=1.2,
            ),
            "get_device_alarms": _device_alarms_tool_result(
                device_code="DEV-005",
                alarm_code="E201",
                alarm_name="振动异常",
            ),
            "search_knowledge": _knowledge_tool_result(
                source="e201_vibration_manual.md#chunk-0",
            ),
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    result = runtime.run(
        [
            LLMMessage(
                role="user",
                content="设备编号: DEV-005\n用户问题: 分析设备振动异常原因",
            )
        ]
    )
    tool_state = _collect_tool_state(result.tool_results)
    search_call = executor.calls[-1]

    assert result.success is True
    assert len(provider.calls) == 2
    assert search_call == (
        "search_knowledge",
        {
            "query": "E201 振动异常 分析设备振动异常原因 motor maintenance handling steps",
            "top_k": 5,
        },
    )
    assert tool_state["sources"] == ["e201_vibration_manual.md#chunk-0"]
    assert json.loads(result.content)["problem_summary"] == "振动参数已超过安全阈值，需要继续诊断。"


def test_runtime_trace_records_router_tools_tool_results_and_rag_results() -> None:
    start_agent_trace(
        mode="runtime",
        query="DEV-001 E203 alarm",
        device_code="DEV-001",
    )
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
    executor = MappingToolExecutor(
        {
            "get_device_status": {
                "tool_name": "get_device_status",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "device_exists": True,
                    "device": {"device_code": "DEV-001"},
                    "latest_runtime_data": {"temperature": 42.0},
                    "recent_alarms": [{"alarm_code": "E203"}],
                    "warnings": [],
                },
                "error": None,
            },
            "search_knowledge": {
                "tool_name": "search_knowledge",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "results": [
                        {
                            "chunk_id": 3,
                            "document_id": 7,
                            "filename": "e203_controller_manual.md",
                            "chunk_index": 0,
                            "content": "E203 handling guide.",
                            "source": "e203_controller_manual.md#chunk-0",
                            "distance": 0.12,
                        }
                    ],
                    "warnings": [],
                },
                "error": None,
            },
        }
    )
    runtime = AgentRuntime(provider, executor)  # type: ignore[arg-type]

    runtime.run([LLMMessage(role="user", content="DEV-001 E203 alarm")])

    trace = get_latest_agent_trace()
    assert trace is not None
    assert trace["router_tools"] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert [result["tool_name"] for result in trace["tool_results"]] == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]
    assert trace["tool_results"][0]["result"]["device_code"] == "DEV-001"
    assert trace["tool_results"][0]["result"]["has_latest_runtime_data"] is True
    assert trace["rag_results"][0] == {
        "chunk_id": 3,
        "document_id": 7,
        "filename": "e203_controller_manual.md",
        "chunk_index": 0,
        "source": "e203_controller_manual.md#chunk-0",
        "distance": 0.12,
        "content": "E203 handling guide.",
        "device_code": "DEV-001",
        "alarm_code": "E203",
        "query": "E203 电机运行异常 DEV-001 E203 alarm maintenance handling steps",
    }


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
    assert "get_device_status, get_device_alarms, and search_knowledge" in system_prompt
    assert "all exceptions" in system_prompt
    assert "call get_device_alarms" in system_prompt
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
    assert "confirmed facts" in system_prompt
    assert "possible_causes" in system_prompt
    assert "verification methods" in system_prompt
    assert "Do not claim a definitive cause" in system_prompt
    assert "risk_level must be one of: low, medium, high, critical, unknown" in (
        system_prompt
    )


def test_runtime_messages_include_explicit_device_code() -> None:
    messages = _build_runtime_messages(
        AgentDiagnoseRequest(
            query="设备当前状态如何？",
            device_code="DEV-001",
        ),
        [],
    )

    assert messages[-1] == {
        "role": "user",
        "content": "设备编号: DEV-001\n用户问题: 设备当前状态如何？",
    }


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


def test_runtime_parse_draft_accepts_loose_json_with_trailing_commas() -> None:
    draft = _parse_runtime_draft(
        """
{
  "problem_summary": "Device status summary.",
  "risk_level": "medium",
  "possible_causes": ["Cooling issue",],
  "recommended_actions": ["Inspect fan",],
}
"""
    )

    assert draft is not None
    assert draft.problem_summary == "Device status summary."
    assert draft.risk_level == "medium"
    assert draft.possible_causes == ["Cooling issue"]
    assert draft.recommended_actions == ["Inspect fan"]


def test_runtime_parse_draft_recovers_plain_text_answer() -> None:
    draft = _parse_runtime_draft(
        """
问题总结：DEV-001 出现 E203 报警并持续升温。
风险等级：高风险
可能原因：
1. 散热异常。
2. 控制器报警未解除。
处理建议：
1. 降低负载。
2. 检查散热和报警记录。
"""
    )

    assert draft is not None
    assert draft.problem_summary == "DEV-001 出现 E203 报警并持续升温。"
    assert draft.risk_level == "high"
    assert draft.possible_causes == ["散热异常。", "控制器报警未解除。"]
    assert draft.recommended_actions == ["降低负载。", "检查散热和报警记录。"]
    assert "最终分析结果不是严格结构化 JSON" in draft.warnings[0]


def test_runtime_parse_draft_logs_raw_response_preview(caplog) -> None:
    caplog.set_level("DEBUG")

    draft = _parse_runtime_draft("问题总结：设备状态需要现场确认。")

    assert draft is not None
    assert "Runtime final raw LLM response preview" in caplog.text


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
    result = _parse_runtime_draft_with_reason("-----")

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


def test_runtime_alarm_overview_query_uses_tools_then_llm(
    monkeypatch,
) -> None:
    provider = FakeToolCallingProvider(
        [
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    {
                        "summary": "LLM generated alarm overview.",
                        "risk_level": "medium",
                        "possible_causes": ["通信链路异常", "电机运行异常"],
                        "suggestions": ["优先处理未解决告警"],
                        "warnings": [],
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )
    executor = MappingToolExecutor(
        {
            "get_device_alarms": {
                "tool_name": "get_device_alarms",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "alarms": [
                        {
                            "device_id": "DEV-001",
                            "alarm_code": "E404",
                            "alarm_name": "通信异常",
                            "level": "low",
                            "status": "unresolved",
                            "created_at": "2026-07-16T15:55:42",
                        },
                        {
                            "device_id": "DEV-001",
                            "alarm_code": "E203",
                            "alarm_name": "电机运行异常",
                            "level": "medium",
                            "status": "unresolved",
                            "created_at": "2026-07-16T15:48:42",
                        },
                    ],
                    "warnings": [],
                },
                "error": None,
            },
            "get_device_status": {
                "tool_name": "get_device_status",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "device_exists": True,
                    "device": {
                        "id": 1,
                        "device_code": "DEV-001",
                        "name": "Pump 1",
                        "device_type": "pump",
                        "location": "Workshop A",
                        "is_online": True,
                        "created_at": "2026-07-16T15:00:00",
                    },
                    "latest_runtime_data": None,
                    "recent_alarms": [],
                    "warnings": [],
                },
                "error": None,
            },
        }
    )
    monkeypatch.setattr("app.agent.runtime.ToolCallExecutor", lambda db: executor)

    response = run_agent_runtime_diagnosis(
        db=object(),
        request=AgentDiagnoseRequest(query="给出所有异常"),
        llm_provider=provider,
    )
    trace = get_latest_agent_trace()

    assert len(provider.calls) == 1
    assert provider.calls[0]["tools"] == []
    assert provider.calls[0]["tool_choice"] == "auto"
    assert "tool_results" in provider.calls[0]["messages"][1]["content"]
    assert executor.calls == [
        ("get_device_alarms", {"device_code": None, "limit": 20, "unresolved_only": True}),
        ("get_device_status", {"device_code": "DEV-001"}),
    ]
    assert response.device is not None
    assert response.device.device_code == "DEV-001"
    assert response.tools_used == ["get_device_alarms", "get_device_status"]
    assert response.possible_causes == ["通信链路异常", "电机运行异常"]
    assert response.recommended_actions == ["优先处理未解决告警"]
    assert response.problem_summary == "LLM generated alarm overview."
    assert trace is not None
    assert trace["router_tools"] == ["get_device_alarms", "get_device_status"]
    assert trace["llm_final_status"]["status"] == "success"


def _device_status_tool_result(
    *,
    device_code: str,
    device_type: str,
    alarm_code: str,
    alarm_message: str,
    vibration: float = 0.2,
) -> dict[str, Any]:
    return {
        "tool_name": "get_device_status",
        "success": True,
        "result": {
            "ok": True,
            "error_code": None,
            "device_exists": True,
            "device": {
                "id": 3,
                "device_code": device_code,
                "name": f"{device_code} Device",
                "device_type": device_type,
                "location": "Workshop C",
                "is_online": True,
                "created_at": "2026-07-16T15:00:00",
            },
            "latest_runtime_data": {
                "id": 30,
                "device_id": 3,
                "temperature": 72.0,
                "voltage": 229.0,
                "current": 4.8,
                "vibration": vibration,
                "status": "warning",
                "recorded_at": "2026-07-16T16:00:00",
                "created_at": "2026-07-16T16:00:01",
            },
            "recent_alarms": [
                {
                    "id": 101,
                    "device_id": 3,
                    "alarm_code": alarm_code,
                    "alarm_level": "medium",
                    "message": alarm_message,
                    "is_resolved": False,
                    "occurred_at": "2026-07-16T15:50:00",
                    "resolved_at": None,
                    "created_at": "2026-07-16T15:50:01",
                }
            ],
            "warnings": [],
        },
        "error": None,
    }


def _device_alarms_tool_result(
    *,
    device_code: str,
    alarm_code: str,
    alarm_name: str,
) -> dict[str, Any]:
    return {
        "tool_name": "get_device_alarms",
        "success": True,
        "result": {
            "ok": True,
            "error_code": None,
            "alarms": [
                {
                    "device_id": device_code,
                    "alarm_code": alarm_code,
                    "alarm_name": alarm_name,
                    "level": "medium",
                    "status": "unresolved",
                    "created_at": "2026-07-16T15:50:00",
                }
            ],
            "warnings": [],
        },
        "error": None,
    }


def _knowledge_tool_result(*, source: str) -> dict[str, Any]:
    return {
        "tool_name": "search_knowledge",
        "success": True,
        "result": {
            "ok": True,
            "error_code": None,
            "results": [
                {
                    "chunk_id": 101,
                    "document_id": 11,
                    "filename": source.split("#", 1)[0],
                    "chunk_index": 0,
                    "content": "E101 temperature anomaly handling steps.",
                    "source": source,
                    "distance": 0.18,
                }
            ],
            "warnings": [],
        },
        "error": None,
    }


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


class MappingToolExecutor:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        if tool_name == "get_device_alarms" and tool_name not in self.results:
            return {
                "tool_name": "get_device_alarms",
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "alarms": [
                        {
                            "device_id": "DEV-001",
                            "alarm_code": "E203",
                            "alarm_name": "电机运行异常",
                            "level": "medium",
                            "status": "unresolved",
                            "created_at": "2026-07-16T15:48:42",
                        }
                    ],
                    "warnings": [],
                },
                "error": None,
            }
        return self.results[tool_name]


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


