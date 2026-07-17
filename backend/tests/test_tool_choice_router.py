import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent.tool_choice_router import (  # noqa: E402
    build_openai_tool_choice,
    route_tool_choices,
)


def test_router_forces_device_tool_for_device_status_query() -> None:
    route = route_tool_choices("查询DEV-001当前状态")

    assert route.tool_names == ["get_device_status"]
    assert route.is_auto is False


def test_router_forces_knowledge_tool_for_alarm_reason_query() -> None:
    route = route_tool_choices("E203报警是什么原因？")

    assert route.tool_names == ["search_knowledge"]


def test_router_forces_two_tools_for_device_alarm_query() -> None:
    route = route_tool_choices("DEV-001 E203报警")

    assert route.tool_names == ["get_device_status", "search_knowledge"]


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
