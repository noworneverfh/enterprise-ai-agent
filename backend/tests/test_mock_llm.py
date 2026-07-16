from datetime import datetime
import socket
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.llm.base import (  # noqa: E402
    LLMMessage,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.mock import MockLLMProvider  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    AgentDiagnoseResponse,
    AgentDiagnosisDraft,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolRuntimeData,
    enforce_minimum_risk_level,
)


def test_agent_diagnosis_draft_accepts_valid_structure() -> None:
    draft = _draft()

    assert draft.problem_summary == "Temperature alarm."
    assert draft.risk_level == "high"
    assert draft.possible_causes == ["Fan failure."]
    assert draft.recommended_actions == ["Stop the device.", "Inspect fan."]


def test_agent_diagnosis_draft_rejects_invalid_risk_level() -> None:
    with pytest.raises(ValidationError):
        _draft(risk_level="severe")


def test_agent_diagnosis_draft_rejects_empty_problem_summary() -> None:
    with pytest.raises(ValidationError):
        _draft(problem_summary="   ")


def test_agent_diagnosis_draft_cleans_empty_list_items() -> None:
    draft = _draft(
        possible_causes=[" Fan failure. ", "", "   "],
        recommended_actions=[" Stop the device. ", "", "Inspect fan."],
        warnings=["", " limited data "],
    )

    assert draft.possible_causes == ["Fan failure."]
    assert draft.recommended_actions == ["Stop the device.", "Inspect fan."]
    assert draft.warnings == ["limited data"]


def test_agent_diagnosis_draft_excludes_program_owned_fields() -> None:
    forbidden_fields = {"device", "device_status", "sources", "tools_used", "disclaimer"}

    assert forbidden_fields.isdisjoint(AgentDiagnosisDraft.model_fields)
    with pytest.raises(ValidationError):
        AgentDiagnosisDraft.model_validate(
            {
                **_draft().model_dump(),
                "sources": ["manual.md#chunk-0"],
            }
        )


def test_agent_diagnose_response_accepts_valid_structure() -> None:
    response = _response()

    assert response.device.device_code == "DEV-001"
    assert response.device_status.status == "warning"
    assert response.recent_alarms[0].alarm_code == "E101"
    assert response.sources == ["manual.md#chunk-0"]
    assert response.tools_used == ["get_device_status", "search_knowledge"]


def test_agent_diagnose_response_rejects_invalid_risk_level() -> None:
    with pytest.raises(ValidationError):
        _response(risk_level="severe")


def test_agent_diagnose_response_requires_list_sources_and_tools_used() -> None:
    with pytest.raises(ValidationError):
        _response(sources="manual.md#chunk-0")

    with pytest.raises(ValidationError):
        _response(tools_used="search_knowledge")


def test_enforce_minimum_risk_level_raises_low_level_to_minimum() -> None:
    assert enforce_minimum_risk_level("low", "high") == "high"


def test_enforce_minimum_risk_level_keeps_higher_proposed_level() -> None:
    assert enforce_minimum_risk_level("critical", "medium") == "critical"


def test_enforce_minimum_risk_level_keeps_low_when_minimum_unknown() -> None:
    assert enforce_minimum_risk_level("low", "unknown") == "low"


def test_enforce_minimum_risk_level_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="Invalid proposed risk level"):
        enforce_minimum_risk_level("severe", "medium")

    with pytest.raises(ValueError, match="Invalid minimum risk level"):
        enforce_minimum_risk_level("low", "severe")


def test_mock_provider_converts_dict_to_structured_model() -> None:
    provider = MockLLMProvider(response=_draft().model_dump())

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert isinstance(result, AgentDiagnosisDraft)
    assert result.risk_level == "high"
    assert len(provider.calls) == 1


def test_mock_provider_returns_existing_pydantic_object() -> None:
    draft = _draft()
    provider = MockLLMProvider(response=draft)

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result is draft


def test_mock_provider_wraps_invalid_output() -> None:
    provider = MockLLMProvider(response={"problem_summary": "", "risk_level": "bad"})

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_mock_provider_can_simulate_timeout() -> None:
    provider = MockLLMProvider(error=LLMTimeoutError("timeout"))

    with pytest.raises(LLMTimeoutError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_mock_provider_can_simulate_unavailable() -> None:
    provider = MockLLMProvider(error=LLMUnavailableError("unavailable"))

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_mock_provider_does_not_require_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_socket(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", fail_socket)
    provider = MockLLMProvider(response=_draft().model_dump())

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "Temperature alarm."


def _messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Return structured JSON."),
        LLMMessage(role="user", content="Diagnose E101."),
    ]


def _draft(**overrides: object) -> AgentDiagnosisDraft:
    data = {
        "problem_summary": "Temperature alarm.",
        "risk_level": "high",
        "possible_causes": ["Fan failure."],
        "recommended_actions": ["Stop the device.", "Inspect fan."],
        "warnings": [],
    }
    data.update(overrides)
    return AgentDiagnosisDraft.model_validate(data)


def _response(**overrides: object) -> AgentDiagnoseResponse:
    now = datetime.utcnow()
    data = {
        "problem_summary": "Temperature alarm.",
        "device": ToolDeviceInfo(
            id=1,
            device_code="DEV-001",
            name="Demo Device",
            device_type="pump",
            location="Workshop A",
            is_online=True,
            created_at=now,
        ),
        "device_status": ToolRuntimeData(
            id=1,
            device_id=1,
            temperature=91.2,
            voltage=220.0,
            current=8.0,
            vibration=0.4,
            status="warning",
            recorded_at=now,
            created_at=now,
        ),
        "recent_alarms": [
            ToolAlarmRecord(
                id=1,
                device_id=1,
                alarm_code="E101",
                alarm_level="high",
                message="High temperature.",
                is_resolved=False,
                occurred_at=now,
                resolved_at=None,
                created_at=now,
            )
        ],
        "risk_level": "high",
        "possible_causes": ["Fan failure."],
        "recommended_actions": ["Stop the device.", "Inspect fan."],
        "sources": ["manual.md#chunk-0"],
        "tools_used": ["get_device_status", "search_knowledge"],
        "warnings": [],
        "disclaimer": "This diagnosis is for operational reference only.",
    }
    data.update(overrides)
    return AgentDiagnoseResponse.model_validate(data)
