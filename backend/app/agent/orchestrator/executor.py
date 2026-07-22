from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.agent import trace as agent_trace
from app.agent import tools as agent_tools
from app.schemas.agent import KnowledgeSearchToolInput
from app.schemas.agent import DeviceAlarmsToolInput, DeviceStatusToolInput
from app.services import device as device_service

from .context import ToolExecutionRecord, now_utc


class ToolExecutionEngine:
    """Execute registered tools through one boundary and record trace."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        trace_context: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        if tool_name == "list_devices":
            return self._execute_list_devices(arguments, trace_context=trace_context)

        started_at = now_utc()
        started = time.perf_counter()
        result = self._execute_registered_tool(tool_name, arguments)
        result = self._attach_trace_context(result, trace_context)
        finished_at = now_utc()
        record = ToolExecutionRecord(
            tool_name=tool_name,
            status="success" if result.get("success") else "failed",
            arguments=self._safe_arguments(arguments),
            result=result.get("result") if isinstance(result.get("result"), dict) else {},
            error_code=result.get("error"),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(1, round((time.perf_counter() - started) * 1000)),
        )
        agent_trace.record_tool_result(result)
        return record

    def search_knowledge(
        self,
        query: str,
        top_k: int,
        *,
        trace_context: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        started_at = now_utc()
        started = time.perf_counter()
        try:
            result_model = self._knowledge_tool()(
                KnowledgeSearchToolInput(query=query, top_k=top_k)
            )
            result = {
                "tool_name": "search_knowledge",
                "success": result_model.ok,
                "result": result_model.model_dump(mode="json"),
                "error": result_model.error_code,
            }
        except Exception:
            result = {
                "tool_name": "search_knowledge",
                "success": False,
                "result": {},
                "error": "tool_execution_failed",
            }

        result = self._attach_trace_context(result, trace_context)
        finished_at = now_utc()
        record = ToolExecutionRecord(
            tool_name="search_knowledge",
            status="success" if result.get("success") else "failed",
            arguments={"query": query, "top_k": top_k},
            result=result.get("result") if isinstance(result.get("result"), dict) else {},
            error_code=result.get("error"),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(1, round((time.perf_counter() - started) * 1000)),
        )
        agent_trace.record_tool_result(result)
        return record

    def _execute_list_devices(
        self,
        arguments: dict[str, Any],
        *,
        trace_context: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        started_at = now_utc()
        started = time.perf_counter()
        try:
            devices = device_service.list_devices(self.db)
            payload = {
                "device_count": len(devices),
                "device_codes": [device.device_code for device in devices],
                "devices": [
                    {
                        "id": device.id,
                        "device_code": device.device_code,
                        "name": device.name,
                        "device_type": device.device_type,
                        "location": device.location,
                        "is_online": device.is_online,
                        "created_at": device.created_at.isoformat(),
                    }
                    for device in devices
                ],
            }
            result = {
                "tool_name": "list_devices",
                "success": True,
                "result": payload,
                "error": None,
            }
        except Exception:
            result = {
                "tool_name": "list_devices",
                "success": False,
                "result": {},
                "error": "tool_execution_failed",
            }

        result = self._attach_trace_context(result, trace_context)
        finished_at = now_utc()
        record = ToolExecutionRecord(
            tool_name="list_devices",
            status="success" if result.get("success") else "failed",
            arguments=self._safe_arguments(arguments),
            result=result.get("result") if isinstance(result.get("result"), dict) else {},
            error_code=result.get("error"),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(1, round((time.perf_counter() - started) * 1000)),
        )
        agent_trace.record_tool_result(result)
        return record

    def _attach_trace_context(
        self,
        tool_result: dict[str, Any],
        trace_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not trace_context or not isinstance(tool_result.get("result"), dict):
            return tool_result
        enriched = dict(tool_result)
        result = dict(enriched["result"])
        result["_trace"] = trace_context
        enriched["result"] = result
        return enriched

    def _safe_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in arguments.items()
            if key.lower() not in {"api_key", "authorization", "token"}
        }

    def _execute_registered_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if tool_name == "get_device_status":
                from app.agent import workflow as workflow_module

                result_model = workflow_module.run_get_device_status_tool(
                    self.db,
                    DeviceStatusToolInput.model_validate(arguments),
                )
            elif tool_name == "get_device_alarms":
                result_model = agent_tools.run_get_device_alarms_tool(
                    self.db,
                    DeviceAlarmsToolInput.model_validate(arguments),
                )
            elif tool_name == "search_knowledge":
                result_model = self._knowledge_tool()(
                    KnowledgeSearchToolInput.model_validate(arguments)
                )
            else:
                return {
                    "tool_name": tool_name,
                    "success": False,
                    "result": {},
                    "error": "tool_not_supported",
                }
            return {
                "tool_name": tool_name,
                "success": bool(getattr(result_model, "ok", True)),
                "result": result_model.model_dump(mode="json"),
                "error": getattr(result_model, "error_code", None),
            }
        except Exception:
            return {
                "tool_name": tool_name,
                "success": False,
                "result": {},
                "error": "tool_execution_failed",
            }

    def _knowledge_tool(self) -> Any:
        from app.agent import risk_analysis as risk_analysis_module
        from app.agent import workflow as workflow_module

        workflow_tool = getattr(workflow_module, "run_search_knowledge_tool", None)
        risk_tool = getattr(risk_analysis_module, "run_search_knowledge_tool", None)
        agent_tool = getattr(agent_tools, "run_search_knowledge_tool")
        if workflow_tool is not None and workflow_tool is not agent_tool:
            return workflow_tool
        if risk_tool is not None and risk_tool is not agent_tool:
            return risk_tool
        return agent_tool
