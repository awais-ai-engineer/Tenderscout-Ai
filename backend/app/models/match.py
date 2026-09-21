from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.analysis import analysis_json

if TYPE_CHECKING:
    from app.models.company import CompanyProfile


class TenderMatch(Base):
    __tablename__ = "tender_matches"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tender_matches"),
        UniqueConstraint(
            "company_id",
            "tender_analysis_id",
            "matcher_version",
            name="uq_matches_identity",
        ),
        CheckConstraint(
            "eligibility_status IN ('eligible', 'ineligible', 'uncertain')",
            name="ck_matches_status",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_matches_score"),
        CheckConstraint(
            "coverage_ratio >= 0 AND coverage_ratio <= 1", name="ck_matches_coverage"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey(
            "company_profiles.id", name="fk_matches_company_id", ondelete="RESTRICT"
        )
    )
    tender_analysis_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tender_analyses.id", name="fk_matches_analysis_id", ondelete="RESTRICT"
        ),
        index=True,
    )
    matcher_version: Mapped[str] = mapped_column(String(32))
    eligibility_status: Mapped[str] = mapped_column(String(16))
    score: Mapped[int | None]
    coverage_ratio: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    company_snapshot: Mapped[dict] = mapped_column(analysis_json)
    hard_blockers: Mapped[list[dict]] = mapped_column(analysis_json)
    matched_requirements: Mapped[list[dict]] = mapped_column(analysis_json)
    unmatched_requirements: Mapped[list[dict]] = mapped_column(analysis_json)
    unknown_requirements: Mapped[list[dict]] = mapped_column(analysis_json)
    capability_matches: Mapped[list[dict]] = mapped_column(analysis_json)
    certification_matches: Mapped[list[dict]] = mapped_column(analysis_json)
    experience_matches: Mapped[list[dict]] = mapped_column(analysis_json)
    risks: Mapped[list[dict]] = mapped_column(analysis_json)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship(back_populates="matches")
