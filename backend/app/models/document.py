from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.tender import Tender


class TenderDocument(Base):
    __tablename__ = "tender_documents"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tender_documents"),
        UniqueConstraint("tender_id", "source_url", name="uq_documents_tender_url"),
        UniqueConstraint(
            "tender_id", "source_document_id", name="uq_documents_tender_source_id"
        ),
        Index("ix_tender_documents_tender_id", "tender_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", name="fk_documents_tender_id", ondelete="RESTRICT")
    )
    source_document_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    tender: Mapped["Tender"] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document_versions"),
        UniqueConstraint(
            "document_id", "content_hash", name="uq_versions_document_hash"
        ),
        CheckConstraint("byte_size > 0", name="ck_versions_positive_size"),
        CheckConstraint(
            "extraction_status IN ('extracted', 'empty', 'failed')",
            name="ck_versions_extraction_status",
        ),
        Index("ix_document_versions_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_documents.id", name="fk_versions_document_id", ondelete="CASCADE"
        )
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int]
    media_type: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(16))
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    document: Mapped[TenderDocument] = relationship(back_populates="versions")
