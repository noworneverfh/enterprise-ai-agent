import logging

from sqlalchemy.orm import Session

from app.schemas.agent import (
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolKnowledgeResult,
    ToolRuntimeData,
)
from app.services import device as device_service
from app.services import knowledge as knowledge_service


logger = logging.getLogger(__name__)


def run_get_device_status_tool(
    db: Session,
    input_data: DeviceStatusToolInput,
) -> DeviceStatusToolResult:
    """Return device status information using the existing device service."""

    try:
        device = device_service.get_device_by_code(db, input_data.device_code)

        if device is None:
            return DeviceStatusToolResult(
                ok=True,
                error_code=None,
                device_exists=False,
                device=None,
                latest_runtime_data=None,
                recent_alarms=[],
                warnings=[f"Device not found: {input_data.device_code}"],
            )

        latest_runtime_data = device_service.get_latest_runtime_data(db, device)
        recent_alarms = device_service.list_alarm_records(
            db,
            device,
            limit=input_data.alarm_limit,
            is_resolved=False,
        )
        warnings: list[str] = []

        if latest_runtime_data is None:
            warnings.append("No runtime data found for device.")

        if not recent_alarms:
            warnings.append("No unresolved alarms found for device.")

        return DeviceStatusToolResult(
            ok=True,
            error_code=None,
            device_exists=True,
            device=ToolDeviceInfo.model_validate(device),
            latest_runtime_data=(
                ToolRuntimeData.model_validate(latest_runtime_data)
                if latest_runtime_data is not None
                else None
            ),
            recent_alarms=[
                ToolAlarmRecord.model_validate(alarm) for alarm in recent_alarms
            ],
            warnings=warnings,
        )
    except Exception:
        logger.exception("Device status tool failed.")
        return DeviceStatusToolResult(
            ok=False,
            error_code="device_query_failed",
            device_exists=None,
            device=None,
            latest_runtime_data=None,
            recent_alarms=[],
            warnings=["Device status query failed."],
        )


def run_search_knowledge_tool(
    input_data: KnowledgeSearchToolInput,
) -> KnowledgeSearchToolResult:
    """Search knowledge chunks using the existing knowledge service."""

    try:
        results = knowledge_service.search_knowledge(
            query=input_data.query,
            top_k=input_data.top_k,
        )
        warnings: list[str] = []

        if not results:
            warnings.append("No knowledge results found.")

        return KnowledgeSearchToolResult(
            ok=True,
            error_code=None,
            results=[
                ToolKnowledgeResult.model_validate(result) for result in results
            ],
            warnings=warnings,
        )
    except Exception:
        logger.exception("Knowledge search tool failed.")
        return KnowledgeSearchToolResult(
            ok=False,
            error_code="knowledge_search_failed",
            results=[],
            warnings=["Knowledge search failed."],
        )
