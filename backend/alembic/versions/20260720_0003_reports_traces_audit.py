"""reports traces audit

Revision ID: 20260720_0003
Revises: 20260720_0002
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch_op:
            if "status" not in user_columns:
                batch_op.add_column(
                    sa.Column(
                        "status",
                        sa.String(length=30),
                        nullable=False,
                        server_default="active",
                    )
                )
            if "last_login_at" not in user_columns:
                batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))

    if "diagnosis_reports" not in inspector.get_table_names():
        op.create_table(
            "diagnosis_reports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("report_id", sa.String(length=64), nullable=False),
            sa.Column("diagnosis_record_id", sa.Integer(), nullable=True),
            sa.Column("report_version", sa.String(length=20), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=True),
            sa.Column("risk_level", sa.String(length=20), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=True),
            sa.Column("confirmed_facts", sa.JSON(), nullable=True),
            sa.Column("parameter_observations", sa.JSON(), nullable=True),
            sa.Column("cause_analysis", sa.JSON(), nullable=True),
            sa.Column("verification_steps", sa.JSON(), nullable=True),
            sa.Column("action_plan", sa.JSON(), nullable=True),
            sa.Column("citations", sa.JSON(), nullable=True),
            sa.Column("provider_type", sa.String(length=50), nullable=True),
            sa.Column("generation_status", sa.String(length=50), nullable=False),
            sa.Column("report_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["diagnosis_record_id"], ["diagnosis_records.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("report_id"),
        )
        op.create_index(op.f("ix_diagnosis_reports_id"), "diagnosis_reports", ["id"])
        op.create_index(op.f("ix_diagnosis_reports_report_id"), "diagnosis_reports", ["report_id"])
        op.create_index(
            op.f("ix_diagnosis_reports_diagnosis_record_id"),
            "diagnosis_reports",
            ["diagnosis_record_id"],
        )
        op.create_index(op.f("ix_diagnosis_reports_device_id"), "diagnosis_reports", ["device_id"])
        op.create_index(op.f("ix_diagnosis_reports_risk_level"), "diagnosis_reports", ["risk_level"])
        op.create_index(op.f("ix_diagnosis_reports_created_at"), "diagnosis_reports", ["created_at"])

    if "diagnosis_traces" not in inspector.get_table_names():
        op.create_table(
            "diagnosis_traces",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.String(length=80), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("step", sa.String(length=80), nullable=False),
            sa.Column("tool_name", sa.String(length=80), nullable=True),
            sa.Column("input_summary", sa.JSON(), nullable=True),
            sa.Column("output_summary", sa.JSON(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_diagnosis_traces_id"), "diagnosis_traces", ["id"])
        op.create_index(op.f("ix_diagnosis_traces_request_id"), "diagnosis_traces", ["request_id"])
        op.create_index(op.f("ix_diagnosis_traces_user_id"), "diagnosis_traces", ["user_id"])
        op.create_index(op.f("ix_diagnosis_traces_report_id"), "diagnosis_traces", ["report_id"])
        op.create_index(op.f("ix_diagnosis_traces_created_at"), "diagnosis_traces", ["created_at"])

    if "audit_logs" not in inspector.get_table_names():
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("username", sa.String(length=80), nullable=True),
            sa.Column("action", sa.String(length=120), nullable=False),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=120), nullable=True),
            sa.Column("result", sa.String(length=30), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"])
        op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"])
        op.create_index(op.f("ix_audit_logs_username"), "audit_logs", ["username"])
        op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
        op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "audit_logs" in inspector.get_table_names():
        op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_username"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
        op.drop_table("audit_logs")
    if "diagnosis_traces" in inspector.get_table_names():
        op.drop_index(op.f("ix_diagnosis_traces_created_at"), table_name="diagnosis_traces")
        op.drop_index(op.f("ix_diagnosis_traces_report_id"), table_name="diagnosis_traces")
        op.drop_index(op.f("ix_diagnosis_traces_user_id"), table_name="diagnosis_traces")
        op.drop_index(op.f("ix_diagnosis_traces_request_id"), table_name="diagnosis_traces")
        op.drop_index(op.f("ix_diagnosis_traces_id"), table_name="diagnosis_traces")
        op.drop_table("diagnosis_traces")
    if "diagnosis_reports" in inspector.get_table_names():
        op.drop_index(op.f("ix_diagnosis_reports_created_at"), table_name="diagnosis_reports")
        op.drop_index(op.f("ix_diagnosis_reports_risk_level"), table_name="diagnosis_reports")
        op.drop_index(op.f("ix_diagnosis_reports_device_id"), table_name="diagnosis_reports")
        op.drop_index(op.f("ix_diagnosis_reports_diagnosis_record_id"), table_name="diagnosis_reports")
        op.drop_index(op.f("ix_diagnosis_reports_report_id"), table_name="diagnosis_reports")
        op.drop_index(op.f("ix_diagnosis_reports_id"), table_name="diagnosis_reports")
        op.drop_table("diagnosis_reports")
    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch_op:
            if "last_login_at" in user_columns:
                batch_op.drop_column("last_login_at")
            if "status" in user_columns:
                batch_op.drop_column("status")
