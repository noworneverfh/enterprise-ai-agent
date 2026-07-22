"""add llm invocations

Revision ID: 20260721_0005
Revises: 20260720_0004
Create Date: 2026-07-21 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0005"
down_revision = "20260720_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_invocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("response_id", sa.String(length=120), nullable=True),
        sa.Column("report_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("base_url_domain", sa.String(length=160), nullable=True),
        sa.Column("mode", sa.String(length=50), nullable=True),
        sa.Column("generation_mode", sa.String(length=50), nullable=False, server_default="real"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("fallback_occurred", sa.String(length=10), nullable=False, server_default="false"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="success"),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("purpose", sa.String(length=50), nullable=False, server_default="business"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_invocations_id"), "llm_invocations", ["id"], unique=False)
    op.create_index(op.f("ix_llm_invocations_request_id"), "llm_invocations", ["request_id"], unique=False)
    op.create_index(op.f("ix_llm_invocations_response_id"), "llm_invocations", ["response_id"], unique=False)
    op.create_index(op.f("ix_llm_invocations_report_id"), "llm_invocations", ["report_id"], unique=False)
    op.create_index(op.f("ix_llm_invocations_user_id"), "llm_invocations", ["user_id"], unique=False)
    op.create_index(op.f("ix_llm_invocations_provider"), "llm_invocations", ["provider"], unique=False)
    op.create_index(op.f("ix_llm_invocations_model"), "llm_invocations", ["model"], unique=False)
    op.create_index(op.f("ix_llm_invocations_status"), "llm_invocations", ["status"], unique=False)
    op.create_index(op.f("ix_llm_invocations_purpose"), "llm_invocations", ["purpose"], unique=False)
    op.create_index(op.f("ix_llm_invocations_created_at"), "llm_invocations", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_invocations_created_at"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_purpose"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_status"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_model"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_provider"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_user_id"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_report_id"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_response_id"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_request_id"), table_name="llm_invocations")
    op.drop_index(op.f("ix_llm_invocations_id"), table_name="llm_invocations")
    op.drop_table("llm_invocations")
