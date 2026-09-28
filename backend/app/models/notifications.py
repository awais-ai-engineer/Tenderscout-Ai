from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import CompanyProfile
    from app.models.tender import Tender


class SavedTender(Base):
    __tablename__ = "saved_tenders"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_saved_tenders"),
        UniqueConstraint("company_id", "tender_id", name="uq_saved_company_tender"),
        Index("ix_saved_tenders_company_id", "company_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="CASCADE")
    )
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship()
    tender: Mapped["Tender"] = relationship()


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        PrimaryKeyConstraint("company_id", name="pk_notification_preferences"),
        CheckConstraint(
            "minimum_match_score >= 0 AND minimum_match_score <= 100",
            name="ck_notification_threshold",
        ),
        CheckConstraint(
            "delivery_mode IN ('instant', 'daily_digest')",
            name="ck_notification_delivery_mode",
        ),
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="CASCADE")
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    notification_email: Mapped[str | None] = mapped_column(String(320))
    minimum_match_score: Mapped[int] = mapped_column(default=70, server_default="70")
    new_match_alerts: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    tender_change_alerts: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    deadline_reminders: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    delivery_mode: Mapped[str] = mapped_column(
        String(16), default="instant", server_default="instant"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_alerts"),
        UniqueConstraint("dedupe_key", name="uq_alerts_dedupe_key"),
        CheckConstraint(
            "type IN ('new_match', 'tender_updated', 'deadline_reminder')",
            name="ck_alert_type",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'unconfigured', 'sent', 'failed')",
            name="ck_alert_delivery_status",
        ),
        Index("ix_alerts_company_created", "company_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="CASCADE")
    )
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    match_id: Mapped[int | None] = mapped_column(
        ForeignKey("tender_matches.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    delivery_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    company: Mapped["CompanyProfile"] = relationship()
    tender: Mapped["Tender"] = relationship()
