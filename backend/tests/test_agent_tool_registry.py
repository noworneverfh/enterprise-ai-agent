import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent.tool_registry import (  # noqa: E402
    get_agent_tool,
    get_agent_tool_registry,
    list_openai_tool_schemas,
    list_agent_tools,
)
from app.schemas.agent import (  # noqa: E402
    DeviceAlarmsToolInput,
    DeviceStatusToolInput,
    KnowledgeSearchToolInput,
)


def test_registry_discovers_existing_agent_tools() -> None:
    tools = list_agent_tools()

    assert [tool.name for tool in tools] == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]
    assert get_agent_tool("get_device_status").input_schema is DeviceStatusToolInput
    assert get_agent_tool("get_device_alarms").input_schema is DeviceAlarmsToolInput
    assert get_agent_tool("search_knowledge").input_schema is KnowledgeSearchToolInput
    assert get_agent_tool("missing_tool") is None


def test_device_status_tool_schema_is_correct() -> None:
    tool = get_agent_tool("get_device_status")

    assert tool is not None
    schema = tool.input_json_schema()
    properties = schema["properties"]

    assert tool.description
    assert schema["title"] == "DeviceStatusToolInput"
    assert schema["required"] == ["device_code"]
    assert properties["device_code"]["type"] == "string"
    assert properties["alarm_limit"]["default"] == 5
    assert properties["alarm_limit"]["minimum"] == 1
    assert properties["alarm_limit"]["maximum"] == 20
    assert "MUST be called" in tool.description
    assert "specific device's current condition" in tool.description


def test_device_alarms_tool_schema_is_correct() -> None:
    tool = get_agent_tool("get_device_alarms")

    assert tool is not None
    schema = tool.input_json_schema()
    properties = schema["properties"]

    assert tool.description
    assert schema["title"] == "DeviceAlarmsToolInput"
    assert properties["device_code"]["anyOf"][0]["type"] == "string"
    assert properties["limit"]["default"] == 20
    assert properties["limit"]["minimum"] == 1
    assert properties["limit"]["maximum"] == 100
    assert properties["unresolved_only"]["default"] is True


def test_knowledge_search_tool_schema_is_correct() -> None:
    tool = get_agent_tool("search_knowledge")

    assert tool is not None
    schema = tool.input_json_schema()
    properties = schema["properties"]

    assert tool.description
    assert schema["title"] == "KnowledgeSearchToolInput"
    assert schema["required"] == ["query"]
    assert properties["query"]["type"] == "string"
    assert properties["top_k"]["default"] == 5
    assert properties["top_k"]["minimum"] == 1
    assert properties["top_k"]["maximum"] == 5


def test_openai_tool_schema_uses_function_format() -> None:
    tool = get_agent_tool("search_knowledge")

    assert tool is not None
    schema = tool.openai_tool_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_knowledge"
    assert schema["function"]["description"] == tool.description
    assert schema["function"]["parameters"]["title"] == "KnowledgeSearchToolInput"


def test_list_openai_tool_schemas_returns_registered_tools() -> None:
    schemas = list_openai_tool_schemas()

    assert [schema["function"]["name"] for schema in schemas] == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]
    assert all(schema["type"] == "function" for schema in schemas)
    assert schemas[0]["function"]["parameters"]["required"] == ["device_code"]
    assert schemas[2]["function"]["parameters"]["required"] == ["query"]


def test_registry_view_is_read_only() -> None:
    registry = get_agent_tool_registry()

    assert set(registry) == {"get_device_status", "get_device_alarms", "search_knowledge"}
    with pytest.raises(TypeError):
        registry["new_tool"] = get_agent_tool("search_knowledge")
