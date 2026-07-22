from datetime import datetime

from app.domain.diagnosis.alarm_catalog import (
    alarm_display_name,
    get_alarm_definition,
)
from app.domain.diagnosis.compatibility import attach_single_report_v2
from app.domain.diagnosis.parameter_rules import evaluate_runtime_parameters
from app.domain.diagnosis.report_builder import (
    build_fleet_risk_report,
    build_single_diagnosis_report,
)
from app.domain.diagnosis.risk_engine import calculate_risk_assessment
from app.schemas.agent import AgentDiagnoseResponse


NOW = datetime(2026, 7, 20, 8, 0, 0)


def test_alarm_catalog_returns_known_and_safe_unknown_names() -> None:
    definition = get_alarm_definition("e101")

    assert definition is not None
    assert definition.name == "温度异常"
    assert definition.related_parameter == "temperature"
    assert alarm_display_name("E999") == "设备异常"


def test_runtime_parameter_rules_are_device_type_aware() -> None:
    runtime = {
        "temperature": 35.0,
        "voltage": 24.1,
        "current": 1.0,
        "vibration": 0.1,
        "recorded_at": NOW,
    }

    sensor = {
        item.parameter: item
        for item in evaluate_runtime_parameters("sensor", runtime)
    }
    motor = {
        item.parameter: item
        for item in evaluate_runtime_parameters("motor", runtime)
    }

    assert sensor["voltage"].status == "normal"
    assert sensor["voltage"].normal_min == 20.0
    assert motor["voltage"].status == "critical"
    assert motor["voltage"].normal_min == 220.0


def test_risk_score_stays_inside_level_band_and_has_breakdown() -> None:
    observations = evaluate_runtime_parameters(
        "motor",
        {
            "temperature": 72.0,
            "voltage": 230.0,
            "current": 9.2,
            "vibration": 0.5,
        },
    )

    risk = calculate_risk_assessment(
        "high",
        observations=observations,
        alarm_levels=["high"],
        is_online=True,
    )

    assert risk.level == "high"
    assert 70 <= risk.score <= 89
    assert {item.code for item in risk.breakdown} >= {
        "alarm_high",
        "parameter_temperature",
    }


def test_single_report_separates_facts_causes_actions_and_citations() -> None:
    report = build_single_diagnosis_report(
        _single_payload(),
        {
            "llm_final_status": {"status": "success"},
            "rag_results": [
                {
                    "source": "e101_maintenance_manual.md#chunk-0",
                    "filename": "e101_maintenance_manual.md",
                    "document_id": 1,
                    "chunk_id": 10,
                    "chunk_index": 0,
                    "content": "E101 温度异常需要检查散热、负载和温度传感器。",
                    "distance": 0.21,
                }
            ],
        },
    )

    assert report.report_version == "2.0"
    assert report.generation_mode == "llm"
    assert any(fact.fact_id.startswith("alarm.E101") for fact in report.confirmed_facts)
    assert report.possible_causes[0].description == "散热不足可能导致温度升高。"
    assert report.possible_causes[0].confidence == "medium"
    assert report.action_plan[0].order == 1
    assert report.citations[0].source == "e101_maintenance_manual.md#chunk-0"
    assert report.citations[0].chunk_id == 10


def test_mock_legacy_summary_is_not_presented_as_v2_diagnosis() -> None:
    payload = _single_payload()
    payload["problem_summary"] = "Mock diagnosis draft generated from tool context."
    payload["warnings"] = ["Mock LLM provider is active."]

    report = build_single_diagnosis_report(payload)

    assert report.generation_mode == "mock"
    assert "Mock" not in report.conclusion
    assert "DEV-003" in report.conclusion
    assert report.action_plan


def test_fleet_report_uses_shared_device_report_structure() -> None:
    payload = {
        "summary": "Analyzed 1 devices; 1 devices have risk signals.",
        "overall_risk_level": "high",
        "device_risks": [
            {
                "device": {
                    "device_code": "DEV-003",
                    "name": "Temperature Sensor C",
                    "device_type": "sensor",
                    "location": "Workshop C",
                    "is_online": True,
                },
                "latest_runtime_data": {
                    "temperature": 72.0,
                    "voltage": 24.0,
                    "current": 1.1,
                    "vibration": 0.1,
                    "recorded_at": NOW,
                },
                "unresolved_alarms": [
                    {
                        "alarm_code": "E101",
                        "alarm_level": "high",
                        "message": "Temperature abnormal",
                        "is_resolved": False,
                    }
                ],
                "risk_level": "high",
                "risk_score": 88,
                "reasons": ["温度超过安全范围。"],
                "knowledge_sources": ["e101_maintenance_manual.md#chunk-0"],
                "recommended_actions": ["检查散热系统和设备负载。"],
            }
        ],
        "sources": ["e101_maintenance_manual.md#chunk-0"],
        "warnings": [],
    }

    report = build_fleet_risk_report(payload)

    assert report.report_version == "2.0"
    assert len(report.devices) == 1
    assert report.devices[0].device_code == "DEV-003"
    assert report.devices[0].risk.level == "high"
    assert report.devices[0].citations[0].source.endswith("#chunk-0")


def test_report_v2_is_opt_in_without_changing_legacy_serialization() -> None:
    response = AgentDiagnoseResponse(
        problem_summary="设备状态需要现场确认。",
        risk_level="unknown",
        disclaimer="辅助诊断结果仅供现场排查参考。",
    )

    assert "report_v2" not in response.model_dump()

    enriched = attach_single_report_v2(response)

    assert enriched.report_v2 is not None
    assert enriched.model_dump()["report_v2"]["report_version"] == "2.0"
    assert response.report_v2 is None


def _single_payload() -> dict:
    return {
        "problem_summary": "DEV-003 存在 E101 温度异常。",
        "device": {
            "device_code": "DEV-003",
            "name": "Temperature Sensor C",
            "device_type": "sensor",
            "location": "Workshop C",
            "is_online": True,
        },
        "device_status": {
            "temperature": 72.0,
            "voltage": 24.0,
            "current": 1.1,
            "vibration": 0.1,
            "recorded_at": NOW,
        },
        "recent_alarms": [
            {
                "alarm_code": "E101",
                "alarm_level": "high",
                "message": "Temperature abnormal",
                "is_resolved": False,
            }
        ],
        "risk_level": "high",
        "possible_causes": ["散热不足可能导致温度升高。"],
        "recommended_actions": ["检查散热系统和设备负载。"],
        "sources": ["e101_maintenance_manual.md#chunk-0"],
        "tools_used": [
            "get_device_status",
            "get_device_alarms",
            "search_knowledge",
        ],
        "warnings": [],
        "disclaimer": "辅助诊断结果仅供现场排查参考。",
    }
