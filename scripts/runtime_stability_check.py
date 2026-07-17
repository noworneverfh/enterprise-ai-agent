import argparse
import logging
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class StabilityCase:
    name: str
    payload: dict[str, Any]
    expected_tools: set[str]


CASES = [
    StabilityCase(
        name="A_DEVICE_STATUS",
        payload={
            "query": "查询DEV-001当前状态",
            "include_device_status": True,
            "include_knowledge": False,
        },
        expected_tools={"get_device_status"},
    ),
    StabilityCase(
        name="B_KNOWLEDGE_ONLY",
        payload={
            "query": "E203报警是什么原因",
            "include_device_status": False,
            "include_knowledge": True,
        },
        expected_tools={"search_knowledge"},
    ),
    StabilityCase(
        name="C_DEVICE_AND_KNOWLEDGE",
        payload={
            "query": "DEV-001出现E203报警，帮我分析",
            "include_device_status": True,
            "include_knowledge": True,
        },
        expected_tools={"get_device_status", "search_knowledge"},
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run temporary Agent Runtime stability checks."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--transport",
        choices=["http", "testclient"],
        default="http",
        help="Use a running HTTP server or FastAPI TestClient.",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        help="Keep application logs visible during the stability run.",
    )
    args = parser.parse_args()

    if not args.verbose_logs:
        logging.disable(logging.CRITICAL)

    rows = []
    if args.transport == "http":
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            timeout=args.timeout,
            limits=limits,
            trust_env=False,
        ) as client:
            for case in CASES:
                rows.append(run_case(client, case, args.iterations))
    else:
        backend_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(backend_dir))
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            for case in CASES:
                rows.append(run_case(client, case, args.iterations))

    print_table(rows)


def run_case(
    client: httpx.Client,
    case: StabilityCase,
    iterations: int,
) -> dict[str, Any]:
    success_count = 0
    fallback_count = 0
    llm_failed_count = 0
    tool_call_success_count = 0
    successful_tools_seen: set[str] = set()
    failed_tools_seen: set[str] = set()
    tool_call_count = 0
    durations: list[float] = []
    failures: list[str] = []

    for index in range(iterations):
        started = time.perf_counter()
        try:
            response = client.post("/agent/diagnose", json=case.payload)
            elapsed_ms = (time.perf_counter() - started) * 1000
            durations.append(elapsed_ms)

            if response.status_code != 200:
                failures.append(f"#{index + 1}: HTTP {response.status_code}")
                continue

            success_count += 1
            body = response.json()
            warnings = body.get("warnings") or []
            warning_text = " | ".join(str(item) for item in warnings)
            successful_tools = set(body.get("tools_used") or [])
            failed_tools = extract_failed_tools(warnings)
            successful_tools_seen.update(successful_tools)
            failed_tools_seen.update(failed_tools)
            tool_call_count += len(successful_tools) + len(failed_tools)

            if contains_fallback(warning_text):
                fallback_count += 1

            if "llm_failed" in warning_text:
                llm_failed_count += 1

            if case.expected_tools.issubset(successful_tools):
                tool_call_success_count += 1
            else:
                failures.append(
                    f"#{index + 1}: successful_tools={sorted(successful_tools)} "
                    f"failed_tools={sorted(failed_tools)} "
                    f"expected={sorted(case.expected_tools)}"
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            durations.append(elapsed_ms)
            failures.append(f"#{index + 1}: {type(exc).__name__}: {exc}")

    return {
        "case": case.name,
        "iterations": iterations,
        "success_count": success_count,
        "fallback_count": fallback_count,
        "llm_failed_count": llm_failed_count,
        "tool_call_success_count": tool_call_success_count,
        "successful_tools": sorted(successful_tools_seen),
        "failed_tools": sorted(failed_tools_seen),
        "tool_call_count": tool_call_count,
        "avg_ms": statistics.mean(durations) if durations else 0.0,
        "failures": failures[:5],
    }


def contains_fallback(warning_text: str) -> bool:
    normalized = warning_text.lower()
    return (
        "fallback" in normalized
        or "unavailable" in normalized
        or "降级" in normalized
        or "不可用" in normalized
    )


def extract_failed_tools(warnings: list[Any]) -> set[str]:
    failed_tools: set[str] = set()
    prefix = "Tool failed:"

    for warning in warnings:
        warning_text = str(warning).strip()
        if not warning_text.startswith(prefix):
            continue

        tool_name = warning_text[len(prefix) :].strip()
        if tool_name:
            failed_tools.add(tool_name)

    return failed_tools


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "case",
        "http_success_rate",
        "fallback_rate",
        "llm_failed_rate",
        "tool_call_success_rate",
        "successful_tools",
        "failed_tools",
        "tool_call_count",
        "average_latency_ms",
    ]
    table_rows = [
        [
            row["case"],
            format_rate(row["success_count"], row["iterations"]),
            format_rate(row["fallback_count"], row["iterations"]),
            format_rate(row["llm_failed_count"], row["iterations"]),
            format_rate(row["tool_call_success_count"], row["iterations"]),
            ",".join(row["successful_tools"]) or "-",
            ",".join(row["failed_tools"]) or "-",
            str(row["tool_call_count"]),
            f"{row['avg_ms']:.1f}",
        ]
        for row in rows
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in table_rows))
        for index in range(len(headers))
    ]

    print(format_row(headers, widths))
    print(format_row(["-" * width for width in widths], widths))
    for row in table_rows:
        print(format_row(row, widths))

    for row in rows:
        if row["failures"]:
            print(f"\n{row['case']} sample failures:")
            for failure in row["failures"]:
                print(f"- {failure}")


def format_row(values: list[str], widths: list[int]) -> str:
    return " | ".join(
        value.ljust(widths[index]) for index, value in enumerate(values)
    )


def format_rate(count: int, total: int) -> str:
    percentage = (count / total * 100) if total else 0
    return f"{count}/{total} ({percentage:.1f}%)"


if __name__ == "__main__":
    main()
