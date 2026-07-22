from collections.abc import Iterable

from app.domain.diagnosis.models import (
    ParameterObservation,
    RiskAssessment,
    RiskScoreItem,
)


RISK_ORDER = {
    "unknown": 0,
    "normal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}
RISK_SCORE_BANDS = {
    "unknown": (0, 0),
    "normal": (5, 19),
    "low": (20, 44),
    "medium": (45, 69),
    "high": (70, 89),
    "critical": (90, 100),
}


def calculate_risk_assessment(
    proposed_level: str,
    *,
    observations: Iterable[ParameterObservation] = (),
    alarm_levels: Iterable[str] = (),
    is_online: bool | None = None,
) -> RiskAssessment:
    normalized_level = proposed_level if proposed_level in RISK_ORDER else "unknown"
    breakdown: list[RiskScoreItem] = []
    evidence_score = 0

    if is_online is False:
        evidence_score += 10
        breakdown.append(
            RiskScoreItem(
                code="device_offline",
                label="设备离线",
                score=10,
                reason="设备当前处于离线状态，实时状态存在信息缺口。",
            )
        )

    for level in alarm_levels:
        normalized_alarm_level = level.strip().lower()
        alarm_score = {
            "low": 4,
            "medium": 8,
            "high": 12,
            "critical": 16,
        }.get(normalized_alarm_level, 0)
        if alarm_score:
            evidence_score += alarm_score
            breakdown.append(
                RiskScoreItem(
                    code=f"alarm_{normalized_alarm_level}",
                    label=f"{normalized_alarm_level} 报警",
                    score=alarm_score,
                    reason="设备存在未解决报警记录。",
                )
            )

    for observation in observations:
        if observation.status == "critical":
            score = 10
        elif observation.status == "warning":
            score = 4
        else:
            continue
        evidence_score += score
        breakdown.append(
            RiskScoreItem(
                code=f"parameter_{observation.parameter}",
                label=f"{observation.label}状态",
                score=score,
                reason=observation.explanation,
            )
        )

    lower, upper = RISK_SCORE_BANDS[normalized_level]
    if normalized_level == "unknown":
        score = 0
    else:
        score = min(upper, lower + evidence_score)

    if not breakdown:
        breakdown.append(
            RiskScoreItem(
                code="risk_level_baseline",
                label="风险等级基线",
                score=lower,
                reason="评分区间与当前确定性风险等级保持一致。",
            )
        )

    return RiskAssessment(
        level=normalized_level,  # type: ignore[arg-type]
        score=score,
        breakdown=breakdown,
    )
