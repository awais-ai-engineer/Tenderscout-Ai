"""Add logical tender documents and immutable content versions."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tender_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.String(255), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(255), nullable=True),
        sa.Column("media_type", sa.String(255), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tender_documents"),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name="fk_documents_tender_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tender_id", "source_url", name="uq_documents_tender_url"),
        sa.UniqueConstraint(
            "tender_id", "source_document_id", name="uq_documents_tender_source_id"
        ),
    )
    op.create_index("ix_tender_documents_tender_id", "tender_documents", ["tender_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(16), nullable=False),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tender_documents.id"],
            name="fk_versions_document_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "content_hash", name="uq_versions_document_hash"
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_versions_positive_size"),
        sa.CheckConstraint(
            "extraction_status IN ('extracted', 'empty', 'failed')",
            name="ck_versions_extraction_status",
        ),
    )
    op.create_index(
        "ix_document_versions_document_id", "document_versions", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_tender_documents_tender_id", table_name="tender_documents")
    op.drop_table("tender_documents")
