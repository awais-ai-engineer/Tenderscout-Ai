from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import DocumentVersion

analysis_json = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True), "postgresql"
)


class TenderAnalysis(Base):
    __tablename__ = "tender_analyses"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tender_analyses"),
        UniqueConstraint(
            "document_version_id",
            "analysis_schema_version",
            "provider",
            "model",
            "prompt_version",
            "input_hash",
            name="uq_analyses_identity",
        ),
        CheckConstraint("status IN ('completed', 'failed')", name="ck_analyses_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_analyses_document_version_id",
            ondelete="RESTRICT",
        )
    )
    analysis_schema_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    raw_response: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_evidence: Mapped[list[str] | None] = mapped_column(analysis_json)
    eligibility_requirements: Mapped[list[dict] | None] = mapped_column(analysis_json)
    required_documents: Mapped[list[dict] | None] = mapped_column(analysis_json)
    technical_requirements: Mapped[list[dict] | None] = mapped_column(analysis_json)
    financial_requirements: Mapped[list[dict] | None] = mapped_column(analysis_json)
    submission_instructions: Mapped[list[dict] | None] = mapped_column(analysis_json)
    evaluation_criteria: Mapped[list[dict] | None] = mapped_column(analysis_json)
    important_dates: Mapped[list[dict] | None] = mapped_column(analysis_json)
    contact_information: Mapped[list[dict] | None] = mapped_column(analysis_json)
    risks_or_ambiguities: Mapped[list[dict] | None] = mapped_column(analysis_json)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    document_version: Mapped["DocumentVersion"] = relationship(
        back_populates="analyses"
    )
