from dataclasses import dataclass


@dataclass(frozen=True)
class AlarmDefinition:
    code: str
    name: str
    category: str
    related_parameter: str | None
    default_level: str
    safety_guidance: str


ALARM_CATALOG: dict[str, AlarmDefinition] = {
    "E101": AlarmDefinition(
        code="E101",
        name="温度异常",
        category="thermal",
        related_parameter="temperature",
        default_level="high",
        safety_guidance="温度持续升高时应降低负载，并评估是否需要安全停机。",
    ),
    "E201": AlarmDefinition(
        code="E201",
        name="振动异常",
        category="mechanical",
        related_parameter="vibration",
        default_level="medium",
        safety_guidance="振动持续升高时应停止高负载运行，并检查机械连接、轴承和安装基础。",
    ),
    "E203": AlarmDefinition(
        code="E203",
        name="电机运行异常",
        category="motor",
        related_parameter="current",
        default_level="medium",
        safety_guidance="电机异常未确认前不应长期强制运行，应重点检查电流、负载和控制回路。",
    ),
    "E404": AlarmDefinition(
        code="E404",
        name="通信异常",
        category="communication",
        related_parameter=None,
        default_level="medium",
        safety_guidance="无法确认设备真实状态时，应避免继续高风险运行，并检查通信链路和网关状态。",
    ),
}


def get_alarm_definition(alarm_code: str) -> AlarmDefinition | None:
    return ALARM_CATALOG.get(alarm_code.strip().upper())


def alarm_display_name(alarm_code: str, fallback: str | None = None) -> str:
    definition = get_alarm_definition(alarm_code)
    if definition is not None:
        return definition.name
    return fallback.strip() if fallback and fallback.strip() else "设备异常"
