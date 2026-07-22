from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from app.domain.diagnosis.models import ParameterObservation


@dataclass(frozen=True)
class ParameterRule:
    parameter: str
    label: str
    unit: str
    normal_min: float
    normal_max: float
    warning_margin_ratio: float = 0.15


DEFAULT_RULES = {
    "temperature": ParameterRule("temperature", "温度", "℃", 0.0, 60.0),
    "voltage": ParameterRule("voltage", "电压", "V", 220.0, 240.0, 0.05),
    "current": ParameterRule("current", "电流", "A", 0.0, 8.0),
    "vibration": ParameterRule("vibration", "振动", "mm/s", 0.0, 0.4),
}

DEVICE_RULES: dict[str, dict[str, ParameterRule]] = {
    "motor": DEFAULT_RULES,
    "sensor": {
        "temperature": ParameterRule("temperature", "温度", "℃", 0.0, 60.0),
        "voltage": ParameterRule("voltage", "电压", "V", 20.0, 28.0, 0.1),
        "current": ParameterRule("current", "电流", "A", 0.0, 2.0),
        "vibration": ParameterRule("vibration", "振动", "mm/s", 0.0, 0.4),
    },
    "compressor": {
        "temperature": ParameterRule("temperature", "温度", "℃", 0.0, 65.0),
        "voltage": ParameterRule("voltage", "电压", "V", 220.0, 240.0, 0.05),
        "current": ParameterRule("current", "电流", "A", 0.0, 10.0),
        "vibration": ParameterRule("vibration", "振动", "mm/s", 0.0, 0.5),
    },
}


def evaluate_runtime_parameters(
    device_type: str | None,
    runtime_data: Mapping[str, object] | None,
) -> list[ParameterObservation]:
    if not runtime_data:
        return []

    rules = DEVICE_RULES.get((device_type or "").strip().lower(), DEFAULT_RULES)
    observed_at = _as_datetime(runtime_data.get("recorded_at"))
    observations: list[ParameterObservation] = []

    for parameter, rule in rules.items():
        value = runtime_data.get(parameter)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue

        numeric_value = float(value)
        status = _parameter_status(numeric_value, rule)
        observations.append(
            ParameterObservation(
                parameter=parameter,
                label=rule.label,
                value=numeric_value,
                unit=rule.unit,
                normal_min=rule.normal_min,
                normal_max=rule.normal_max,
                status=status,
                explanation=_explanation(numeric_value, rule, status),
                observed_at=observed_at,
            )
        )

    return observations


def _parameter_status(value: float, rule: ParameterRule) -> str:
    if value < rule.normal_min or value > rule.normal_max:
        return "critical"

    operating_span = rule.normal_max - rule.normal_min
    margin = operating_span * rule.warning_margin_ratio
    if value <= rule.normal_min + margin or value >= rule.normal_max - margin:
        return "warning"

    return "normal"


def _explanation(value: float, rule: ParameterRule, status: str) -> str:
    normal_range = f"{rule.normal_min:g}-{rule.normal_max:g}{rule.unit}"
    if status == "critical":
        direction = "低于" if value < rule.normal_min else "超过"
        return f"当前值{direction}该设备类型对应的安全范围 {normal_range}。"
    if status == "warning":
        return f"当前值接近该设备类型对应的安全边界 {normal_range}。"
    return f"当前值处于该设备类型对应的安全范围 {normal_range} 内。"


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
