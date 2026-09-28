from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.analysis import analysis_json


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint("run_type = 'source_pipeline'", name="ck_pipeline_type"),
        CheckConstraint(
            "source_slug IN ('find-a-tender', 'contracts-finder', 'ted')",
            name="ck_pipeline_source",
        ),
        CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name="ck_pipeline_trigger"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_pipeline_status",
        ),
        Index(
            "uq_pipeline_active_source",
            "source_slug",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(String(32), default="source_pipeline")
    source_slug: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    celery_task_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[dict] = mapped_column(analysis_json, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(String(160))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_run_id",
            "stage",
            "entity_type",
            "entity_id",
            name="uq_pipeline_stage_identity",
        ),
        CheckConstraint(
            "stage IN ('ingest', 'documents', 'analysis', "
            "'indexing', 'matching', 'changes')",
            name="ck_pipeline_stage",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'skipped', 'failed')",
            name="ck_pipeline_stage_status",
        ),
        CheckConstraint(
            "entity_type IN ('source', 'document_version', 'analysis')",
            name="ck_pipeline_entity",
        ),
        CheckConstraint("entity_id >= 0", name="ck_pipeline_entity_id"),
        CheckConstraint("attempt BETWEEN 0 AND 4", name="ck_pipeline_attempt"),
        Index(
            "ix_pipeline_stage_eligibility",
            "stage",
            "entity_type",
            "entity_id",
            "config_key",
            "status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT", name="fk_stage_run")
    )
    parent_stage_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "pipeline_stage_runs.id", ondelete="RESTRICT", name="fk_stage_parent"
        ),
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    entity_type: Mapped[str] = mapped_column(String(24))
    entity_id: Mapped[int]
    config_key: Mapped[str] = mapped_column(String(64), default="v1")
    attempt: Mapped[int] = mapped_column(default=0)
    metrics: Mapped[dict] = mapped_column(analysis_json, default=dict)
    scope_ids: Mapped[list[int]] = mapped_column(analysis_json, default=list)
    failure_reason: Mapped[str | None] = mapped_column(String(160))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
