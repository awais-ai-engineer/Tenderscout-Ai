"""Add immutable tender revisions and deterministic change sets."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tender_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("revision_index", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision_index >= 1", name="ck_revisions_index"),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name="fk_revisions_tender",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tender_revisions"),
        sa.UniqueConstraint("tender_id", "revision_index", name="uq_revisions_index"),
    )
    op.create_table(
        "tender_metadata_change_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("from_revision_id", sa.Integer(), nullable=False),
        sa.Column("to_revision_id", sa.Integer(), nullable=False),
        sa.Column("changeset_version", sa.String(length=32), nullable=False),
        sa.Column("has_changes", sa.Boolean(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column(
            "changed_fields",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "changes",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("change_count >= 0", name="ck_metadata_changes_count"),
        sa.CheckConstraint(
            "from_revision_id <> to_revision_id", name="ck_metadata_changes_distinct"
        ),
        sa.ForeignKeyConstraint(
            ["from_revision_id"],
            ["tender_revisions.id"],
            name="fk_metadata_changes_from_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name="fk_metadata_changes_tender",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_revision_id"],
            ["tender_revisions.id"],
            name="fk_metadata_changes_to_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metadata_change_sets"),
        sa.UniqueConstraint(
            "from_revision_id",
            "to_revision_id",
            "changeset_version",
            name="uq_metadata_changes_identity",
        ),
    )
    op.create_index(
        op.f("ix_tender_metadata_change_sets_tender_id"),
        "tender_metadata_change_sets",
        ["tender_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tender_metadata_change_sets_to_revision_id"),
        "tender_metadata_change_sets",
        ["to_revision_id"],
        unique=False,
    )
    op.create_table(
        "document_analysis_change_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_document_id", sa.Integer(), nullable=False),
        sa.Column("from_analysis_id", sa.Integer(), nullable=False),
        sa.Column("to_analysis_id", sa.Integer(), nullable=False),
        sa.Column("changeset_version", sa.String(length=32), nullable=False),
        sa.Column("has_changes", sa.Boolean(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column(
            "category_counts",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "changes",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("change_count >= 0", name="ck_document_changes_count"),
        sa.CheckConstraint(
            "from_analysis_id <> to_analysis_id", name="ck_document_changes_distinct"
        ),
        sa.ForeignKeyConstraint(
            ["from_analysis_id"],
            ["tender_analyses.id"],
            name="fk_document_changes_from_analysis",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tender_document_id"],
            ["tender_documents.id"],
            name="fk_document_changes_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_analysis_id"],
            ["tender_analyses.id"],
            name="fk_document_changes_to_analysis",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_analysis_change_sets"),
        sa.UniqueConstraint(
            "from_analysis_id",
            "to_analysis_id",
            "changeset_version",
            name="uq_document_changes_identity",
        ),
    )
    op.create_index(
        op.f("ix_document_analysis_change_sets_tender_document_id"),
        "document_analysis_change_sets",
        ["tender_document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_analysis_change_sets_to_analysis_id"),
        "document_analysis_change_sets",
        ["to_analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("document_analysis_change_sets")
    op.drop_table("tender_metadata_change_sets")
    op.drop_table("tender_revisions")
