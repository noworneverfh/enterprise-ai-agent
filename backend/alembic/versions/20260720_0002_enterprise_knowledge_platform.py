"""enterprise knowledge platform

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0002"
down_revision: str | None = "20260719_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("device_type", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch_op.create_index(
            "ix_knowledge_documents_device_type",
            ["device_type"],
            unique=False,
        )

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.add_column(sa.Column("section", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("page", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunk_metadata", sa.JSON(), nullable=True))
        batch_op.create_index(
            "ix_knowledge_chunks_section",
            ["section"],
            unique=False,
        )

    op.create_table(
        "fault_knowledge_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("fault_code", sa.String(length=30), nullable=False),
        sa.Column("fault_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("device_type", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("trigger_conditions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fault_knowledge_entries_id"),
        "fault_knowledge_entries",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fault_knowledge_entries_document_id"),
        "fault_knowledge_entries",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fault_knowledge_entries_fault_code"),
        "fault_knowledge_entries",
        ["fault_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fault_knowledge_entries_severity"),
        "fault_knowledge_entries",
        ["severity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fault_knowledge_entries_device_type"),
        "fault_knowledge_entries",
        ["device_type"],
        unique=False,
    )

    op.create_table(
        "fault_causes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fault_entry_id", sa.Integer(), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fault_entry_id"], ["fault_knowledge_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fault_causes_id"), "fault_causes", ["id"], unique=False)
    op.create_index(
        op.f("ix_fault_causes_fault_entry_id"),
        "fault_causes",
        ["fault_entry_id"],
        unique=False,
    )

    op.create_table(
        "inspection_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fault_entry_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("safety_requirement", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fault_entry_id"], ["fault_knowledge_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inspection_steps_id"), "inspection_steps", ["id"], unique=False)
    op.create_index(
        op.f("ix_inspection_steps_fault_entry_id"),
        "inspection_steps",
        ["fault_entry_id"],
        unique=False,
    )

    op.create_table(
        "maintenance_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fault_entry_id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fault_entry_id"], ["fault_knowledge_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_actions_id"),
        "maintenance_actions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_actions_fault_entry_id"),
        "maintenance_actions",
        ["fault_entry_id"],
        unique=False,
    )

    op.create_table(
        "maintenance_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fault_entry_id", sa.Integer(), nullable=True),
        sa.Column("device", sa.String(length=120), nullable=False),
        sa.Column("fault", sa.String(length=120), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("solution", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fault_entry_id"], ["fault_knowledge_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_cases_id"),
        "maintenance_cases",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_cases_fault_entry_id"),
        "maintenance_cases",
        ["fault_entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_maintenance_cases_fault_entry_id"), table_name="maintenance_cases")
    op.drop_index(op.f("ix_maintenance_cases_id"), table_name="maintenance_cases")
    op.drop_table("maintenance_cases")
    op.drop_index(op.f("ix_maintenance_actions_fault_entry_id"), table_name="maintenance_actions")
    op.drop_index(op.f("ix_maintenance_actions_id"), table_name="maintenance_actions")
    op.drop_table("maintenance_actions")
    op.drop_index(op.f("ix_inspection_steps_fault_entry_id"), table_name="inspection_steps")
    op.drop_index(op.f("ix_inspection_steps_id"), table_name="inspection_steps")
    op.drop_table("inspection_steps")
    op.drop_index(op.f("ix_fault_causes_fault_entry_id"), table_name="fault_causes")
    op.drop_index(op.f("ix_fault_causes_id"), table_name="fault_causes")
    op.drop_table("fault_causes")
    op.drop_index(op.f("ix_fault_knowledge_entries_device_type"), table_name="fault_knowledge_entries")
    op.drop_index(op.f("ix_fault_knowledge_entries_severity"), table_name="fault_knowledge_entries")
    op.drop_index(op.f("ix_fault_knowledge_entries_fault_code"), table_name="fault_knowledge_entries")
    op.drop_index(op.f("ix_fault_knowledge_entries_document_id"), table_name="fault_knowledge_entries")
    op.drop_index(op.f("ix_fault_knowledge_entries_id"), table_name="fault_knowledge_entries")
    op.drop_table("fault_knowledge_entries")

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.drop_index("ix_knowledge_chunks_section")
        batch_op.drop_column("chunk_metadata")
        batch_op.drop_column("page")
        batch_op.drop_column("section")

    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.drop_index("ix_knowledge_documents_device_type")
        batch_op.drop_column("effective_date")
        batch_op.drop_column("model")
        batch_op.drop_column("device_type")
        batch_op.drop_column("source")
        batch_op.drop_column("version")
        batch_op.drop_column("title")
