import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


def test_alembic_head_creates_production_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "migration_check.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

    result = subprocess.run(
        [
            str((PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").resolve()),
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    assert {
        "users",
        "roles",
        "permissions",
        "devices",
        "device_runtime_data",
        "device_alarm_records",
        "knowledge_documents",
        "knowledge_chunks",
        "fault_knowledge_entries",
        "diagnosis_records",
        "diagnosis_reports",
        "diagnosis_traces",
        "audit_logs",
    }.issubset(tables)
