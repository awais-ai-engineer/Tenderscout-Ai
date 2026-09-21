"""Add append-only structured analysis results."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tender_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("analysis_schema_version", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "summary_evidence", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "eligibility_requirements",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "required_documents", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "technical_requirements", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "financial_requirements", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "submission_instructions",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "evaluation_criteria", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "important_dates", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "contact_information", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "risks_or_ambiguities", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tender_analyses"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_analyses_document_version_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "analysis_schema_version",
            "provider",
            "model",
            "prompt_version",
            "input_hash",
            name="uq_analyses_identity",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')", name="ck_analyses_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("tender_analyses")
