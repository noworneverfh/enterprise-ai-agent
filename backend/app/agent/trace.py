from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


_current_trace: ContextVar[dict[str, Any] | None] = ContextVar(
    "current_agent_trace",
    default=None,
)
_latest_trace: dict[str, Any] | None = None
_latest_trace_lock = Lock()


def start_agent_trace(
    *,
    mode: str,
    query: str,
    device_code: str | None,
) -> dict[str, Any]:
    trace = {
        "trace_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "query": query,
        "device_code": device_code,
        "router_tools": [],
        "tool_results": [],
        "rag_results": [],
        "llm_final_status": None,
    }
    _current_trace.set(trace)
    _set_latest_trace(trace)
    return trace


def record_router_selection(tool_names: list[str]) -> None:
    trace = _current_trace.get()
    if trace is None:
        return

    trace["router_tools"] = list(tool_names)
    _set_latest_trace(trace)


def record_tool_result(tool_result: dict[str, Any]) -> None:
    trace = _current_trace.get()
    if trace is None:
        return

    summary = _summarize_tool_result(tool_result)
    trace["tool_results"].append(summary)

    if summary["tool_name"] == "search_knowledge":
        trace["rag_results"].extend(_summarize_rag_results(tool_result))

    _set_latest_trace(trace)


def record_llm_final_status(
    *,
    status: str,
    fallback_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    trace = _current_trace.get()
    if trace is None:
        return

    trace["llm_final_status"] = {
        "status": status,
        "fallback_reason": fallback_reason,
        "metadata": metadata or {},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _set_latest_trace(trace)


def record_device_context(context: dict[str, Any]) -> None:
    trace = _current_trace.get()
    if trace is None:
        return

    trace["device_context"] = context
    _set_latest_trace(trace)


def get_latest_agent_trace() -> dict[str, Any] | None:
    with _latest_trace_lock:
        if _latest_trace is None:
            return None
        return deepcopy(_latest_trace)


def _set_latest_trace(trace: dict[str, Any]) -> None:
    global _latest_trace
    with _latest_trace_lock:
        _latest_trace = deepcopy(trace)


def _summarize_tool_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    tool_name = tool_result.get("tool_name")
    result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    summary: dict[str, Any] = {
        "tool_name": tool_name,
        "success": bool(tool_result.get("success")),
        "error": tool_result.get("error"),
    }

    if tool_name == "list_devices":
        summary["result"] = {
            "device_count": result.get("device_count"),
            "device_codes": result.get("device_codes")
            if isinstance(result.get("device_codes"), list)
            else [],
        }
    elif tool_name == "get_device_status":
        trace_context = result.get("_trace") if isinstance(result.get("_trace"), dict) else {}
        device = result.get("device") if isinstance(result.get("device"), dict) else None
        runtime_data = result.get("latest_runtime_data")
        recent_alarms = result.get("recent_alarms")
        summary["result"] = {
            "ok": result.get("ok"),
            "device_exists": result.get("device_exists"),
            "device_code": trace_context.get("device_code")
            or (device.get("device_code") if device is not None else None),
            "has_latest_runtime_data": runtime_data is not None,
            "recent_alarm_count": (
                len(recent_alarms) if isinstance(recent_alarms, list) else 0
            ),
        }
    elif tool_name == "get_device_alarms":
        trace_context = result.get("_trace") if isinstance(result.get("_trace"), dict) else {}
        alarms = result.get("alarms")
        if not isinstance(alarms, list):
            alarms = []
        summary["result"] = {
            "ok": result.get("ok"),
            "device_code": trace_context.get("device_code"),
            "alarm_count": len(alarms),
            "alarms": [
                {
                    "device_id": item.get("device_id"),
                    "alarm_code": item.get("alarm_code"),
                    "alarm_name": item.get("alarm_name"),
                    "level": item.get("level"),
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                }
                for item in alarms
                if isinstance(item, dict)
            ][:20],
        }
    elif tool_name == "search_knowledge":
        trace_context = result.get("_trace") if isinstance(result.get("_trace"), dict) else {}
        results = result.get("results")
        summary["result"] = {
            "ok": result.get("ok"),
            "device_code": trace_context.get("device_code"),
            "alarm_code": trace_context.get("alarm_code"),
            "query": trace_context.get("query"),
            "result_count": len(results) if isinstance(results, list) else 0,
            "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
        }
    else:
        summary["result"] = {}

    return summary


def _summarize_rag_results(tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    result = tool_result.get("result")
    if not isinstance(result, dict):
        return []

    trace_context = result.get("_trace") if isinstance(result.get("_trace"), dict) else {}
    raw_results = result.get("results")
    if not isinstance(raw_results, list):
        return []

    rag_results: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        rag_result = {
            "chunk_id": item.get("chunk_id"),
            "document_id": item.get("document_id"),
            "filename": item.get("filename"),
            "chunk_index": item.get("chunk_index"),
            "source": item.get("source"),
            "distance": item.get("distance"),
            "content": _preview_text(item.get("content")),
        }
        if item.get("vector_score") is not None:
            rag_result["vector_score"] = item.get("vector_score")
        if item.get("rerank_score") is not None:
            rag_result["rerank_score"] = item.get("rerank_score")
        if trace_context.get("device_code") is not None:
            rag_result["device_code"] = trace_context.get("device_code")
        if trace_context.get("alarm_code") is not None:
            rag_result["alarm_code"] = trace_context.get("alarm_code")
        if trace_context.get("query") is not None:
            rag_result["query"] = trace_context.get("query")
        rag_results.append(rag_result)
    return rag_results


def _preview_text(value: object, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized

    return f"{normalized[:limit]}..."
