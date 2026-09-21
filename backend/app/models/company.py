from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.match import TenderMatch


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_company_profiles"),
        CheckConstraint("employee_count >= 0", name="ck_company_employee_count"),
        CheckConstraint("annual_revenue >= 0", name="ck_company_annual_revenue"),
        CheckConstraint("years_in_business >= 0", name="ck_company_years"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(2048))
    employee_count: Mapped[int | None]
    annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    years_in_business: Mapped[int | None]
    capabilities_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    certifications_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    experience_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    financials_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    capabilities: Mapped[list["CompanyCapability"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CompanyCapability.id",
    )
    certifications: Mapped[list["CompanyCertification"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CompanyCertification.id",
    )
    experience: Mapped[list["CompanyExperience"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CompanyExperience.id",
    )
    matches: Mapped[list["TenderMatch"]] = relationship(
        back_populates="company", passive_deletes="all"
    )


class CompanyCapability(Base):
    __tablename__ = "company_capabilities"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_company_capabilities"),
        UniqueConstraint("company_id", "name_key", name="uq_capabilities_company_name"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey(
            "company_profiles.id",
            name="fk_company_capabilities_company_id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    name_key: Mapped[str] = mapped_column(String(765))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship(back_populates="capabilities")


class CompanyCertification(Base):
    __tablename__ = "company_certifications"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_company_certifications"),
        CheckConstraint("valid_until >= valid_from", name="ck_certification_dates"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey(
            "company_profiles.id",
            name="fk_company_certifications_company_id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    issuer: Mapped[str | None] = mapped_column(String(255))
    identifier: Mapped[str | None] = mapped_column(String(255))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship(back_populates="certifications")


class CompanyExperience(Base):
    __tablename__ = "company_experience"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_company_experience"),
        CheckConstraint("contract_value >= 0", name="ck_experience_value"),
        CheckConstraint("completed_at >= started_at", name="ck_experience_dates"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey(
            "company_profiles.id",
            name="fk_company_experience_company_id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255))
    client: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(255))
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    started_at: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    company: Mapped["CompanyProfile"] = relationship(back_populates="experience")
