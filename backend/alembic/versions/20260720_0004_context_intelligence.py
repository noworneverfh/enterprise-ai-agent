"""context intelligence memory layer

Revision ID: 20260720_0004
Revises: 20260720_0003
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0004"
down_revision: str | None = "20260720_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "diagnosis_sessions" not in tables:
        op.create_table(
            "diagnosis_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("request_id", sa.String(length=80), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("device_id", sa.Integer(), nullable=True),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("intent", sa.String(length=80), nullable=True),
            sa.Column("planned_tools", sa.JSON(), nullable=True),
            sa.Column("evidence_summary", sa.JSON(), nullable=True),
            sa.Column("rag_summary", sa.JSON(), nullable=True),
            sa.Column("risk_summary", sa.JSON(), nullable=True),
            sa.Column("report_summary", sa.JSON(), nullable=True),
            sa.Column("feedback_summary", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id"),
        )
        _index("diagnosis_sessions", "session_id")
        _index("diagnosis_sessions", "request_id")
        _index("diagnosis_sessions", "user_id")
        _index("diagnosis_sessions", "device_id")
        _index("diagnosis_sessions", "report_id")
        _index("diagnosis_sessions", "created_at")

    if "device_context_snapshots" not in tables:
        op.create_table(
            "device_context_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("risk_level", sa.String(length=20), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("device_context_snapshots", "device_id")
        _index("device_context_snapshots", "risk_level")
        _index("device_context_snapshots", "generated_at")

    if "device_risk_timeline" not in tables:
        op.create_table(
            "device_risk_timeline",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=False),
            sa.Column("risk_level", sa.String(length=20), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=False),
            sa.Column("alarm_count", sa.Integer(), nullable=False),
            sa.Column("abnormal_parameters", sa.JSON(), nullable=True),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("device_risk_timeline", "device_id")
        _index("device_risk_timeline", "risk_level")
        _index("device_risk_timeline", "report_id")
        _index("device_risk_timeline", "recorded_at")

    if "maintenance_records" not in tables:
        op.create_table(
            "maintenance_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=False),
            sa.Column("alarm_record_id", sa.Integer(), nullable=True),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("ai_recommendation", sa.JSON(), nullable=True),
            sa.Column("actual_action", sa.Text(), nullable=False),
            sa.Column("confirmed_root_cause", sa.Text(), nullable=True),
            sa.Column("resolved", sa.Boolean(), nullable=False),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("performed_by", sa.Integer(), nullable=True),
            sa.Column("performed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["alarm_record_id"], ["device_alarm_records.id"]),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("maintenance_records", "device_id")
        _index("maintenance_records", "alarm_record_id")
        _index("maintenance_records", "report_id")
        _index("maintenance_records", "performed_by")
        _index("maintenance_records", "created_at")

    if "diagnosis_feedback" not in tables:
        op.create_table(
            "diagnosis_feedback",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("report_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("helpful", sa.Boolean(), nullable=True),
            sa.Column("corrected_cause", sa.Text(), nullable=True),
            sa.Column("corrected_action", sa.Text(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("diagnosis_feedback", "report_id")
        _index("diagnosis_feedback", "user_id")
        _index("diagnosis_feedback", "created_at")

    if "risk_events" not in tables:
        op.create_table(
            "risk_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.String(length=64), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("risk_level", sa.String(length=20), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id"),
        )
        _index("risk_events", "event_id")
        _index("risk_events", "device_id")
        _index("risk_events", "event_type")
        _index("risk_events", "risk_level")
        _index("risk_events", "status")
        _index("risk_events", "report_id")
        _index("risk_events", "created_at")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in [
        "risk_events",
        "diagnosis_feedback",
        "maintenance_records",
        "device_risk_timeline",
        "device_context_snapshots",
        "diagnosis_sessions",
    ]:
        if table in tables:
            for index in inspector.get_indexes(table):
                op.drop_index(index["name"], table_name=table)
            op.drop_table(table)


def _index(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)
