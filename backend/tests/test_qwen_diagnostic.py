import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import workflow  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.llm.base import LLMStructuredOutputError, StructuredModel  # noqa: E402
from app.llm.factory import get_llm_provider  # noqa: E402
from app.llm.openai_compatible import MARKDOWN_JSON_PATTERN  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolKnowledgeResult,
    ToolRuntimeData,
)

logger = logging.getLogger(__name__)


class DiagnosticOpenAICompatibleProvider(OpenAICompatibleProvider):
    def complete_structured(
        self,
        messages: list,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        payload = self._build_payload(messages)

        if self._client is not None:
            response = self._post_with_retries(payload, self._client)
        else:
            import httpx

            with httpx.Client() as client:
                response = self._post_with_retries(payload, client)

        content = self._extract_content(response)
        logger.info("Qwen raw content: %s", content)

        stripped = content.strip()
        match = MARKDOWN_JSON_PATTERN.match(stripped)
        if match is not None:
            stripped = match.group(1).strip()

        logger.info("Qwen stripped content before json.loads: %s", stripped)

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            logger.info("Qwen json.loads error: %s: %s", type(exc).__name__, exc)
            raise LLMStructuredOutputError(
                "LLM response content is not valid JSON."
            ) from exc

        logger.info(
            "Qwen data before model validation: %s",
            json.dumps(data, ensure_ascii=False, indent=2),
        )

        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            logger.info("Qwen model validation error: %s: %s", type(exc).__name__, exc)
            raise LLMStructuredOutputError(
                "LLM output failed schema validation."
            ) from exc


def test_qwen_diagnostic_agent_diagnose(monkeypatch):
    monkeypatch.setattr(workflow, "run_get_device_status_tool", _device_tool)
    monkeypatch.setattr(workflow, "run_search_knowledge_tool", _knowledge_tool)

    def override_get_db():
        yield object()

    real_provider = get_llm_provider()
    diagnostic_provider = DiagnosticOpenAICompatibleProvider(
        api_key=real_provider._api_key,
        base_url=real_provider.base_url,
        model=real_provider.model,
        timeout_seconds=real_provider.timeout_seconds,
        max_retries=real_provider.max_retries,
        temperature=real_provider.temperature,
        max_tokens=real_provider.max_tokens,
        json_mode=real_provider.json_mode,
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: diagnostic_provider

    try:
        response = TestClient(app).post(
            "/agent/diagnose",
            json={
                "query": "DEV-001 出现 E101 报警并持续升温，应该怎么处理？",
                "knowledge_top_k": 3,
                "include_device_status": True,
                "include_knowledge": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    logger.info(
        "Agent diagnostic response: %s",
        json.dumps(response.json(), ensure_ascii=False, indent=2),
    )

    assert response.status_code == 200


def _device_tool(db: object, input_data: DeviceStatusToolInput) -> DeviceStatusToolResult:
    now = datetime.utcnow()
    return DeviceStatusToolResult(
        ok=True,
        device_exists=True,
        device=ToolDeviceInfo(
            id=1,
            device_code=input_data.device_code,
            name="Demo Device",
            device_type="pump",
            location="Workshop A",
            is_online=True,
            created_at=now,
        ),
        latest_runtime_data=ToolRuntimeData(
            id=1,
            device_id=1,
            temperature=93.5,
            voltage=220.0,
            current=8.4,
            vibration=0.6,
            status="warning",
            recorded_at=now,
            created_at=now,
        ),
        recent_alarms=[
            ToolAlarmRecord(
                id=1,
                device_id=1,
                alarm_code="E101",
                alarm_level="high",
                message="High temperature alarm.",
                is_resolved=False,
                occurred_at=now,
                resolved_at=None,
                created_at=now,
            )
        ],
    )


def _knowledge_tool(input_data: KnowledgeSearchToolInput) -> KnowledgeSearchToolResult:
    return KnowledgeSearchToolResult(
        ok=True,
        results=[
            ToolKnowledgeResult(
                chunk_id=1,
                document_id=1,
                filename="e101_maintenance_manual.md",
                chunk_index=0,
                content=(
                    "E101 indicates high temperature. Check cooling fan, "
                    "airflow blockage, temperature sensor, and sustained load."
                ),
                source="e101_maintenance_manual.md#chunk-0",
                distance=0.18,
            )
        ],
    )
