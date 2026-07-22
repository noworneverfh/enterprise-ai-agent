from __future__ import annotations

from app.context.schemas import DeviceContext


def build_context_aware_queries(
    *,
    user_query: str,
    device_context: DeviceContext | None,
    base_queries: list[tuple[str, str | None]],
) -> list[tuple[str, str | None]]:
    """Rewrite RAG queries with device context while preserving alarm-specific routing."""

    if device_context is None or not device_context.exists:
        return base_queries

    enhanced: list[tuple[str, str | None]] = []
    for query, alarm_code in base_queries:
        enhanced_query = _enhance_query(query, alarm_code, user_query, device_context)
        if (enhanced_query, alarm_code) not in enhanced:
            enhanced.append((enhanced_query, alarm_code))
    return enhanced


def _enhance_query(
    query: str,
    alarm_code: str | None,
    user_query: str,
    context: DeviceContext,
) -> str:
    device = context.device
    parts: list[str] = [query, user_query]
    if device is not None:
        parts.extend([device.device_code, device.device_type, device.name])

    if alarm_code:
        parts.extend(_alarm_terms(context, alarm_code))
    else:
        parts.extend(
            f"{alarm.alarm_code} {alarm.alarm_name}"
            for alarm in context.current_alarms[:3]
        )

    if context.health_summary is not None:
        parts.extend(context.health_summary.abnormal_parameters)

    parts.extend(
        f"{item.risk_level} risk {','.join(item.abnormal_parameters)}"
        for item in context.risk_trend[:3]
    )
    parts.extend(
        f"{memory.confirmed_root_cause or ''} {memory.actual_action} {memory.result or ''}"
        for memory in context.maintenance_memory[:3]
    )
    parts.extend(
        f"{case.fault} {case.symptom} {case.root_cause} {case.solution}"
        for case in context.similar_cases[:3]
    )
    parts.extend(
        f"{knowledge.fault_code} {knowledge.fault_name} {knowledge.device_type or ''}"
        for knowledge in context.related_knowledge[:5]
        if not alarm_code or knowledge.fault_code == alarm_code
    )
    parts.append("maintenance troubleshooting root cause verification")
    return _dedupe_join(parts)


def _alarm_terms(context: DeviceContext, alarm_code: str) -> list[str]:
    terms: list[str] = []
    for alarm in [*context.current_alarms, *context.historical_alarms]:
        if alarm.alarm_code.upper() == alarm_code.upper():
            terms.append(f"{alarm.alarm_code} {alarm.alarm_name} {alarm.message}")
    return terms


def _dedupe_join(parts: list[str | None]) -> str:
    result: list[str] = []
    for part in parts:
        if not part:
            continue
        normalized = " ".join(str(part).split())
        if normalized and normalized not in result:
            result.append(normalized)
    return " ".join(result)
