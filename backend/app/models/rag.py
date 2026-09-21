from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.analysis import analysis_json
from app.rag.config import VECTOR_DIMENSIONS


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document_chunks"),
        UniqueConstraint(
            "document_version_id",
            "chunker_version",
            "chunk_index",
            name="uq_chunks_identity",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_chunks_index"),
        CheckConstraint(
            "start_char >= 0 AND end_char > start_char", name="ck_chunks_offsets"
        ),
        CheckConstraint(
            "chunk_size >= 256 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_chunks_config",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey(
            "document_versions.id", name="fk_chunks_version", ondelete="RESTRICT"
        ),
        index=True,
    )
    chunk_index: Mapped[int]
    chunker_version: Mapped[str] = mapped_column(String(32))
    chunk_size: Mapped[int]
    chunk_overlap: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int]
    end_char: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_chunk_embeddings"),
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "dimensions",
            "input_hash",
            name="uq_embeddings_identity",
        ),
        CheckConstraint("dimensions = 1536", name="ck_embeddings_dimensions"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey(
            "document_chunks.id", name="fk_embeddings_chunk", ondelete="RESTRICT"
        ),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(255))
    dimensions: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(VECTOR_DIMENSIONS).with_variant(JSON(), "sqlite")
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenderQuestion(Base):
    __tablename__ = "tender_questions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tender_questions"),
        UniqueConstraint(
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
        CheckConstraint(
            "status IN ('completed', 'insufficient', 'failed')",
            name="ck_questions_status",
        ),
        CheckConstraint("top_k >= 1 AND top_k <= 20", name="ck_questions_top_k"),
        CheckConstraint("embedding_dimensions = 1536", name="ck_questions_dimensions"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey(
            "document_versions.id", name="fk_questions_version", ondelete="RESTRICT"
        ),
        index=True,
    )
    question: Mapped[str] = mapped_column(Text)
    question_hash: Mapped[str] = mapped_column(String(64))
    embedding_provider: Mapped[str] = mapped_column(String(50))
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_dimensions: Mapped[int]
    answer_provider: Mapped[str] = mapped_column(String(50))
    answer_model: Mapped[str] = mapped_column(String(255))
    chunker_version: Mapped[str] = mapped_column(String(32))
    retrieval_version: Mapped[str] = mapped_column(String(32))
    answer_prompt_version: Mapped[str] = mapped_column(String(32))
    top_k: Mapped[int]
    max_context_chars: Mapped[int]
    context_hash: Mapped[str] = mapped_column(String(64))
    retrieval_succeeded: Mapped[bool] = mapped_column(Boolean)
    context_chunk_ids: Mapped[list[int]] = mapped_column(analysis_json)
    status: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(analysis_json)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
