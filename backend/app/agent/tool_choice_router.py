import re
from dataclasses import dataclass
from typing import Any


DEVICE_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])DEV-\d+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
ALARM_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])E\d{3,}(?![A-Za-z0-9])",
    re.IGNORECASE,
)

STATUS_KEYWORDS = [
    "\u72b6\u6001",  # 状态
    "\u5f53\u524d",  # 当前
    "\u8fd0\u884c",  # 运行
    "\u5728\u7ebf",  # 在线
    "\u53c2\u6570",  # 参数
    "\u6570\u636e",  # 数据
    "\u6b63\u5e38\u5417",  # 正常吗
    "\u8bbe\u5907\u4fe1\u606f",  # 设备信息
    "\u60c5\u51b5",  # 情况
]
ALARM_OVERVIEW_KEYWORDS = [
    "\u6240\u6709\u5f02\u5e38",  # 所有异常
    "\u5168\u90e8\u5f02\u5e38",  # 全部异常
    "\u6240\u6709\u62a5\u8b66",  # 所有报警
    "\u5168\u90e8\u62a5\u8b66",  # 全部报警
    "\u5f53\u524d\u62a5\u8b66",  # 当前报警
    "\u5f53\u524d\u6709\u54ea\u4e9b\u62a5\u8b66",  # 当前有哪些报警
    "\u67e5\u770b\u8bbe\u5907\u5f02\u5e38",  # 查看设备异常
    "\u5f02\u5e38\u5217\u8868",  # 异常列表
    "\u62a5\u8b66\u5217\u8868",  # 报警列表
    "\u6709\u54ea\u4e9b\u5f02\u5e38",  # 有哪些异常
    "\u6709\u54ea\u4e9b\u62a5\u8b66",  # 有哪些报警
    "\u7ed9\u51fa\u6240\u6709\u5f02\u5e38",  # 给出所有异常
    "\u628a\u6240\u6709\u5f02\u5e38\u7ed9\u6211",  # 把所有异常给我
]
KNOWLEDGE_KEYWORDS = [
    "\u62a5\u8b66",  # 报警
    "\u6545\u969c",  # 故障
    "\u5f02\u5e38",  # 异常
    "\u539f\u56e0",  # 原因
    "\u7ef4\u4fee",  # 维修
    "\u5904\u7406",  # 处理
    "\u89e3\u51b3",  # 解决
    "\u65b9\u6cd5",  # 方法
    "\u600e\u4e48\u5904\u7406",  # 怎么处理
    "\u5982\u4f55\u7ef4\u4fee",  # 如何维修
    "\u6e29\u5ea6",  # 温度
    "\u632f\u52a8",  # 振动
    "\u7535\u6d41",  # 电流
    "\u7535\u538b",  # 电压
    "\u901a\u4fe1",  # 通信
    "E101",
    "E201",
    "E203",
    "E404",
]
REPAIR_KEYWORDS = [
    "\u600e\u4e48\u5904\u7406",  # 怎么处理
    "\u5982\u4f55\u7ef4\u4fee",  # 如何维修
    "\u7ef4\u4fee",  # 维修
    "\u5904\u7406",  # 处理
    "\u89e3\u51b3",  # 解决
    "\u65b9\u6cd5",  # 方法
]
CAUSE_KEYWORDS = [
    "\u539f\u56e0",  # 原因
    "\u4e3a\u4ec0\u4e48",  # 为什么
    "\u662f\u4ec0\u4e48\u539f\u56e0",  # 是什么原因
    "\u5206\u6790",  # 分析
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

    normalized_query = query.strip()
    has_device = DEVICE_CODE_PATTERN.search(normalized_query) is not None
    has_alarm = ALARM_CODE_PATTERN.search(normalized_query) is not None
    has_status_keyword = any(keyword in normalized_query for keyword in STATUS_KEYWORDS)
    has_alarm_overview_keyword = any(
        keyword in normalized_query for keyword in ALARM_OVERVIEW_KEYWORDS
    )
    has_fault_knowledge_keyword = any(
        keyword.lower() in normalized_query.lower() for keyword in KNOWLEDGE_KEYWORDS
    )
    has_repair_keyword = any(keyword in normalized_query for keyword in REPAIR_KEYWORDS)
    has_cause_keyword = any(keyword in normalized_query for keyword in CAUSE_KEYWORDS)

    if has_alarm_overview_keyword:
        return ToolChoiceRoute(["get_device_alarms", "get_device_status"])

    if has_status_keyword and not has_fault_knowledge_keyword:
        return ToolChoiceRoute(["get_device_status"])

    if has_device and (has_alarm or has_repair_keyword or has_cause_keyword):
        return ToolChoiceRoute(
            ["get_device_status", "get_device_alarms", "search_knowledge"]
        )

    if has_device and has_fault_knowledge_keyword:
        return ToolChoiceRoute(
            ["get_device_status", "get_device_alarms", "search_knowledge"]
        )

    if has_alarm and (has_repair_keyword or has_cause_keyword):
        return ToolChoiceRoute(["get_device_alarms", "search_knowledge"])

    if has_fault_knowledge_keyword:
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
