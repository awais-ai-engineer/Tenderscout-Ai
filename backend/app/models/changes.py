from datetime import datetime

from sqlalchemy import (
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


class TenderRevision(Base):
    __tablename__ = "tender_revisions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tender_revisions"),
        UniqueConstraint("tender_id", "revision_index", name="uq_revisions_index"),
        CheckConstraint("revision_index >= 1", name="ck_revisions_index"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", name="fk_revisions_tender", ondelete="RESTRICT")
    )
    revision_index: Mapped[int]
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_content_hash: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenderMetadataChangeSet(Base):
    __tablename__ = "tender_metadata_change_sets"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_metadata_change_sets"),
        UniqueConstraint(
            "from_revision_id",
            "to_revision_id",
            "changeset_version",
            name="uq_metadata_changes_identity",
        ),
        CheckConstraint(
            "from_revision_id <> to_revision_id", name="ck_metadata_changes_distinct"
        ),
        CheckConstraint("change_count >= 0", name="ck_metadata_changes_count"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tenders.id", name="fk_metadata_changes_tender", ondelete="RESTRICT"
        ),
        index=True,
    )
    from_revision_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_revisions.id",
            name="fk_metadata_changes_from_revision",
            ondelete="RESTRICT",
        )
    )
    to_revision_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_revisions.id",
            name="fk_metadata_changes_to_revision",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    changeset_version: Mapped[str] = mapped_column(String(32))
    has_changes: Mapped[bool] = mapped_column(Boolean)
    change_count: Mapped[int]
    changed_fields: Mapped[list[str]] = mapped_column(analysis_json)
    changes: Mapped[list[dict]] = mapped_column(analysis_json)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentAnalysisChangeSet(Base):
    __tablename__ = "document_analysis_change_sets"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_document_analysis_change_sets"),
        UniqueConstraint(
            "from_analysis_id",
            "to_analysis_id",
            "changeset_version",
            name="uq_document_changes_identity",
        ),
        CheckConstraint(
            "from_analysis_id <> to_analysis_id", name="ck_document_changes_distinct"
        ),
        CheckConstraint("change_count >= 0", name="ck_document_changes_count"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_document_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_documents.id",
            name="fk_document_changes_document",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    from_analysis_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_analyses.id",
            name="fk_document_changes_from_analysis",
            ondelete="RESTRICT",
        )
    )
    to_analysis_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_analyses.id",
            name="fk_document_changes_to_analysis",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    changeset_version: Mapped[str] = mapped_column(String(32))
    has_changes: Mapped[bool] = mapped_column(Boolean)
    change_count: Mapped[int]
    category_counts: Mapped[dict[str, int]] = mapped_column(analysis_json)
    changes: Mapped[list[dict]] = mapped_column(analysis_json)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
