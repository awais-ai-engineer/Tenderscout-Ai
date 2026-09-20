from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.tender import Tender


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sources"),
        UniqueConstraint("slug", name="uq_sources_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenders: Mapped[list["Tender"]] = relationship(
        back_populates="source", passive_deletes="all"
    )
