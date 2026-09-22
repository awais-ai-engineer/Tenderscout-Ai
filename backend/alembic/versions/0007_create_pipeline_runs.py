"""Add durable source pipeline runs and stage state."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("source_slug", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("celery_task_id", sa.String(length=36), nullable=False),
        sa.Column(
            "summary",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.String(length=160), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("run_type = 'source_pipeline'", name="ck_pipeline_type"),
        sa.CheckConstraint(
            "source_slug IN ('find-a-tender', 'contracts-finder')",
            name="ck_pipeline_source",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_pipeline_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name="ck_pipeline_trigger"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_pipeline_active_source",
        "pipeline_runs",
        ["source_slug"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "pipeline_stage_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("parent_stage_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("entity_type", sa.String(length=24), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("config_key", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "metrics",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.Column(
            "scope_ids",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.String(length=160), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('source', 'document_version', 'analysis')",
            name="ck_pipeline_entity",
        ),
        sa.CheckConstraint(
            "stage IN ('ingest', 'documents', 'analysis', "
            "'indexing', 'matching', 'changes')",
            name="ck_pipeline_stage",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'skipped', 'failed')",
            name="ck_pipeline_stage_status",
        ),
        sa.CheckConstraint("attempt BETWEEN 0 AND 4", name="ck_pipeline_attempt"),
        sa.CheckConstraint("entity_id >= 0", name="ck_pipeline_entity_id"),
        sa.ForeignKeyConstraint(
            ["parent_stage_id"],
            ["pipeline_stage_runs.id"],
            name="fk_stage_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_stage_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_run_id",
            "stage",
            "entity_type",
            "entity_id",
            name="uq_pipeline_stage_identity",
        ),
    )
    op.create_index(
        "ix_pipeline_stage_eligibility",
        "pipeline_stage_runs",
        ["stage", "entity_type", "entity_id", "config_key", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_stage_runs_parent_stage_id"),
        "pipeline_stage_runs",
        ["parent_stage_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("pipeline_stage_runs")
    op.drop_table("pipeline_runs")
