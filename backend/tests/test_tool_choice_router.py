import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent.tool_choice_router import (  # noqa: E402
    build_openai_tool_choice,
    route_tool_choices,
)


def test_router_forces_alarm_tool_for_all_exceptions_query() -> None:
    route = route_tool_choices("把所有异常给我")

    assert route.tool_names == ["get_device_alarms", "get_device_status"]
    assert route.is_auto is False


def test_router_forces_alarm_and_device_tool_for_give_all_exceptions_query() -> None:
    route = route_tool_choices("给出所有异常")

    assert route.tool_names == ["get_device_alarms", "get_device_status"]


def test_router_forces_alarm_tool_for_current_alarm_query() -> None:
    route = route_tool_choices("当前有哪些报警")

    assert route.tool_names == ["get_device_alarms", "get_device_status"]


def test_router_forces_device_tool_for_device_status_query() -> None:
    route = route_tool_choices("查询DEV-001当前状态")

    assert route.tool_names == ["get_device_status"]
    assert route.is_auto is False


def test_router_forces_device_tool_for_status_query_without_device_code() -> None:
    route = route_tool_choices("设备当前状态如何")

    assert route.tool_names == ["get_device_status"]


def test_router_forces_device_tool_with_explicit_device_code_message() -> None:
    route = route_tool_choices("设备编号: DEV-001\n用户问题: 设备当前状态如何？")

    assert route.tool_names == ["get_device_status"]



def test_router_does_not_search_knowledge_for_plain_status_analysis() -> None:
    route = route_tool_choices(
        "\u8bbe\u5907\u7f16\u53f7: DEV-004\n"
        "\u7528\u6237\u95ee\u9898: \u5206\u6790\u5f53\u524d\u8bbe\u5907\u72b6\u6001"
    )

    assert route.tool_names == ["get_device_status"]

def test_router_forces_knowledge_tool_for_alarm_reason_query() -> None:
    route = route_tool_choices("E203报警是什么原因？")

    assert route.tool_names == ["get_device_alarms", "search_knowledge"]


def test_router_forces_three_tools_for_device_alarm_query() -> None:
    route = route_tool_choices("DEV-001 E203报警")

    assert route.tool_names == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_router_forces_three_tools_with_explicit_device_code_and_alarm_query() -> None:
    route = route_tool_choices("设备编号: DEV-001\n用户问题: E203报警如何处理")

    assert route.tool_names == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_router_forces_three_tools_for_device_fault_description() -> None:
    route = route_tool_choices("设备编号: DEV-003\n用户问题: 分析温度异常原因")

    assert route.tool_names == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_router_uses_auto_for_general_query() -> None:
    route = route_tool_choices("你好")

    assert route.tool_names == []
    assert route.is_auto is True


def test_build_openai_tool_choice() -> None:
    assert build_openai_tool_choice(None) == "auto"
    assert build_openai_tool_choice("get_device_status") == {
        "type": "function",
        "function": {"name": "get_device_status"},
    }
