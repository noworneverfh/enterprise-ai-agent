import re
from dataclasses import dataclass
from typing import Any


DEVICE_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])DEV-\d+(?![A-Za-z0-9])", re.IGNORECASE)
ALARM_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])E\d{3,}(?![A-Za-z0-9])", re.IGNORECASE)
STATUS_KEYWORDS = [
    "状态",
    "当前",
    "在线",
    "运行",
    "运行情况",
    "设备信息",
]
KNOWLEDGE_KEYWORDS = [
    "原因",
    "处理",
    "维修",
    "方法",
    "怎么办",
    "怎么处理",
    "故障",
]


@dataclass(frozen=True)
class ToolChoiceRoute:
    """Deterministic tool choice plan before asking the LLM."""

    tool_names: list[str]

    @property
    def is_auto(self) -> bool:
        return not self.tool_names


def route_tool_choices(query: str) -> ToolChoiceRoute:
    """Route a user query to forced tools, or leave tool choice as auto."""

    has_device = DEVICE_CODE_PATTERN.search(query) is not None
    has_alarm = ALARM_CODE_PATTERN.search(query) is not None
    has_status_keyword = any(keyword in query for keyword in STATUS_KEYWORDS)
    has_knowledge_keyword = any(keyword in query for keyword in KNOWLEDGE_KEYWORDS)

    if has_device and has_alarm:
        return ToolChoiceRoute(["get_device_status", "search_knowledge"])

    if has_device and has_status_keyword:
        return ToolChoiceRoute(["get_device_status"])

    if has_alarm and has_knowledge_keyword:
        return ToolChoiceRoute(["search_knowledge"])

    return ToolChoiceRoute([])


def build_openai_tool_choice(tool_name: str | None) -> str | dict[str, Any]:
    """Build an OpenAI-compatible tool_choice value."""

    if tool_name is None:
        return "auto"

    return {
        "type": "function",
        "function": {
            "name": tool_name,
        },
    }
