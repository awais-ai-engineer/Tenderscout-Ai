"""Add document chunks, pgvector embeddings and cited question history."""

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(length=32), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_chunks_index"),
        sa.CheckConstraint(
            "chunk_size >= 256 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_chunks_config",
        ),
        sa.CheckConstraint(
            "start_char >= 0 AND end_char > start_char", name="ck_chunks_offsets"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_chunks_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunker_version",
            "chunk_index",
            name="uq_chunks_identity",
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_document_version_id"),
        "document_chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_table(
        "tender_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_provider", sa.String(length=50), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("answer_provider", sa.String(length=50), nullable=False),
        sa.Column("answer_model", sa.String(length=255), nullable=False),
        sa.Column("chunker_version", sa.String(length=32), nullable=False),
        sa.Column("retrieval_version", sa.String(length=32), nullable=False),
        sa.Column("answer_prompt_version", sa.String(length=32), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("max_context_chars", sa.Integer(), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("retrieval_succeeded", sa.Boolean(), nullable=False),
        sa.Column(
            "context_chunk_ids",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "citations",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'insufficient', 'failed')",
            name="ck_questions_status",
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 1536", name="ck_questions_dimensions"
        ),
        sa.CheckConstraint("top_k >= 1 AND top_k <= 20", name="ck_questions_top_k"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_questions_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tender_questions"),
        sa.UniqueConstraint(
            "document_version_id",
            "question_hash",
            "embedding_provider",
            "embedding_model",
            "embedding_dimensions",
            "answer_provider",
            "answer_model",
            "chunker_version",
            "retrieval_version",
            "answer_prompt_version",
            "top_k",
            "max_context_chars",
            "context_hash",
            "retrieval_succeeded",
            name="uq_questions_identity",
        ),
    )
    op.create_index(
        op.f("ix_tender_questions_document_version_id"),
        "tender_questions",
        ["document_version_id"],
        unique=False,
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            VECTOR(dim=1536).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("dimensions = 1536", name="ck_embeddings_dimensions"),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name="fk_embeddings_chunk",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunk_embeddings"),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "dimensions",
            "input_hash",
            name="uq_embeddings_identity",
        ),
    )
    op.create_index(
        op.f("ix_chunk_embeddings_chunk_id"),
        "chunk_embeddings",
        ["chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_table("tender_questions")
    op.drop_table("document_chunks")
    # The shared vector extension may be used outside these tables.
