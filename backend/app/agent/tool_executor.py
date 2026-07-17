import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agent import tools as agent_tools
from app.agent.tool_registry import get_agent_tool


logger = logging.getLogger(__name__)


class ToolCallExecutor:
    """Execute registered agent tools behind a stable result boundary."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | str,
    ) -> dict[str, Any]:
        tool = get_agent_tool(tool_name)
        if tool is None:
            return self._error_result(
                tool_name=tool_name,
                error_code="tool_not_found",
            )

        try:
            parsed_arguments = self._parse_arguments(arguments)
            input_data = tool.input_schema.model_validate(parsed_arguments)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return self._error_result(
                tool_name=tool_name,
                error_code="invalid_arguments",
            )

        try:
            if tool_name == "get_device_status":
                result = agent_tools.run_get_device_status_tool(self.db, input_data)
            elif tool_name == "search_knowledge":
                result = agent_tools.run_search_knowledge_tool(input_data)
            else:
                return self._error_result(
                    tool_name=tool_name,
                    error_code="tool_not_supported",
                )
        except Exception:
            logger.exception("Agent tool execution failed. tool_name=%s", tool_name)
            return self._error_result(
                tool_name=tool_name,
                error_code="tool_execution_failed",
            )

        return {
            "tool_name": tool_name,
            "success": True,
            "result": self._serialize_result(result),
            "error": None,
        }

    def _parse_arguments(self, arguments: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments

        if isinstance(arguments, str):
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            return parsed

        raise TypeError("Tool arguments must be a dict or JSON object string.")

    def _serialize_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")

        if isinstance(result, dict):
            return result

        raise TypeError("Tool result must be a Pydantic model or dict.")

    def _error_result(self, tool_name: str, error_code: str) -> dict[str, Any]:
        return {
            "tool_name": tool_name,
            "success": False,
            "result": {},
            "error": error_code,
        }
