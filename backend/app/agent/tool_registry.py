from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from app.schemas.agent import DeviceStatusToolInput, KnowledgeSearchToolInput


@dataclass(frozen=True)
class AgentToolDefinition:
    """Metadata for a tool that can be exposed to a future LLM tool caller."""

    name: str
    description: str
    input_schema: type[BaseModel]

    def input_json_schema(self) -> dict[str, Any]:
        return self.input_schema.model_json_schema()

    def openai_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_json_schema(),
            },
        }


_TOOL_REGISTRY: dict[str, AgentToolDefinition] = {
    "get_device_status": AgentToolDefinition(
        name="get_device_status",
        description=(
            "Query equipment basic information, online status, latest runtime data, "
            "and recent unresolved alarms by device code. This tool MUST be called "
            "before answering any question about a specific device's current condition."
        ),
        input_schema=DeviceStatusToolInput,
    ),
    "search_knowledge": AgentToolDefinition(
        name="search_knowledge",
        description=(
            "Search maintenance knowledge chunks for fault codes, symptoms, "
            "and troubleshooting questions."
        ),
        input_schema=KnowledgeSearchToolInput,
    ),
}


def list_agent_tools() -> list[AgentToolDefinition]:
    """Return all registered agent tools in deterministic order."""

    return list(_TOOL_REGISTRY.values())


def list_openai_tool_schemas() -> list[dict[str, Any]]:
    """Return registered tools in OpenAI-compatible function tool format."""

    return [tool.openai_tool_schema() for tool in list_agent_tools()]


def get_agent_tool(name: str) -> AgentToolDefinition | None:
    """Return one registered agent tool by name."""

    return _TOOL_REGISTRY.get(name)


def get_agent_tool_registry() -> MappingProxyType[str, AgentToolDefinition]:
    """Return a read-only view of the tool registry."""

    return MappingProxyType(_TOOL_REGISTRY)
