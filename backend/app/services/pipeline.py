"""Durable operational state; no broker, HTTP or provider calls in transactions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PipelineRun, PipelineStageRun
from app.services.change_rules import utc_datetime
from app.sources import SOURCE_CONNECTORS

SOURCES = tuple(SOURCE_CONNECTORS)
ACTIVE = ("queued", "running")
TERMINAL = ("completed", "skipped", "failed")


class Stage(StrEnum):
    INGEST = "ingest"
    DOCUMENTS = "documents"
    ANALYSIS = "analysis"
    INDEXING = "indexing"
    MATCHING = "matching"
    CHANGES = "changes"


class Reason(StrEnum):
    UNSUPPORTED = "Document processing is not supported for this source"
    NO_WORK = "No eligible work"
    AI_CONFIG = "Required AI configuration is unavailable"
    ANALYSIS_FAILED = "Analysis returned a durable failed result"
    DISABLED = "Automatic company matching is disabled"
    NO_PREVIOUS = "No previous compatible completed analysis"
    SOURCE = "Source fetch or validation failed"
    DATABASE = "Database operation failed"
    PROVIDER = "Provider operation failed"
    INVALID = "Stage input or business rule validation failed"
    UNEXPECTED = "Stage execution failed unexpectedly"
    PUBLISH = "Broker publication failed or delivery is uncertain"
    STALE = "Worker execution did not finalize before stale threshold"
    CONFIG_CHANGED = "Worker processing configuration changed during run"


METRICS = frozenset(
    {
        "discovered",
        "created",
        "changed",
        "unchanged",
        "failed",
        "skipped",
        "metadata_created",
        "metadata_changed",
        "metadata_unchanged",
        "versions_created",
        "content_unchanged",
        "extracted",
        "empty",
        "chunks_created",
        "chunks_reused",
        "embeddings_created",
        "embeddings_reused",
        "analysis_id",
        "reused",
        "matched",
        "change_set_id",
        "change_count",
        "limited",
        "scope_count",
    }
)


@dataclass(frozen=True)
class StageSpec:
    stage: Stage
    entity_type: str = "source"
    entity_id: int = 0
    config_key: str = "v1"
    scope_ids: list[int] = field(default_factory=list)


@dataclass
class Outcome:
    status: str = "completed"
    metrics: dict = field(default_factory=dict)
    reason: Reason | None = None
    children: list[StageSpec] = field(default_factory=list)


def validate_metrics(metrics: dict) -> dict:
    if set(metrics) - METRICS or any(
        type(value) not in (int, bool) or not 0 <= value <= 10**9
        for value in metrics.values()
    ):
        raise ValueError("Metrics must be allowlisted bounded numeric counters")
    return dict(metrics)


def stage_row(run_id: int, spec: StageSpec, parent_id: int | None = None):
    Stage(spec.stage)
    if len(spec.scope_ids) > 500 or any(
        type(i) is not int or i <= 0 for i in spec.scope_ids
    ):
        raise ValueError("Scope must contain at most 500 positive IDs")
    return PipelineStageRun(
        pipeline_run_id=run_id,
        parent_stage_id=parent_id,
        stage=spec.stage,
        entity_type=spec.entity_type,
        entity_id=spec.entity_id,
        config_key=spec.config_key,
        scope_ids=sorted(set(spec.scope_ids)),
    )


def create_run(
    engine: Engine, source: str, trigger: str = "manual"
) -> tuple[int, bool]:
    if source not in SOURCES or trigger not in ("manual", "scheduled"):
        raise ValueError("Unsupported source or trigger")
    try:
        with Session(engine) as session, session.begin():
            run = PipelineRun(
                source_slug=source, trigger=trigger, celery_task_id=str(uuid4())
            )
            session.add(run)
            session.flush()
            session.add(stage_row(run.id, StageSpec(Stage.INGEST)))
            return run.id, False
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(
                select(PipelineRun.id).where(
                    PipelineRun.source_slug == source, PipelineRun.status.in_(ACTIVE)
                )
            )
            if existing is not None:
                return existing, True
        raise


def load_stage(engine: Engine, stage_id: int) -> tuple[PipelineStageRun, PipelineRun]:
    with Session(engine) as session:
        row = session.get(PipelineStageRun, stage_id)
        if row is None:
            raise ValueError("Stage does not exist")
        return row, session.get(PipelineRun, row.pipeline_run_id)


def lock_rows(session: Session, stage_id: int):
    run_id = session.scalar(
        select(PipelineStageRun.pipeline_run_id).where(PipelineStageRun.id == stage_id)
    )
    if run_id is None:
        raise ValueError("Stage does not exist")
    run = session.scalar(
        select(PipelineRun).where(PipelineRun.id == run_id).with_for_update()
    )
    row = session.scalar(
        select(PipelineStageRun)
        .where(PipelineStageRun.id == stage_id)
        .with_for_update()
    )
    return row, run


def claim_stage(
    engine: Engine, stage_id: int
) -> tuple[PipelineStageRun, PipelineRun] | None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        row, run = lock_rows(session, stage_id)
        if run.status not in ACTIVE or row.status != "queued" or row.attempt >= 4:
            return None
        now = datetime.now(UTC)
        row.status, row.started_at, row.finished_at = "running", now, None
        row.attempt += 1
        run.status = "running"
        run.started_at = run.started_at or now
        return row, run


def finalize(session: Session, run: PipelineRun) -> None:
    """Caller locks the run. Child insertion and parent completion are atomic."""
    session.flush()
    rows = session.scalars(
        select(PipelineStageRun).where(PipelineStageRun.pipeline_run_id == run.id)
    ).all()
    if run.status not in ACTIVE or any(row.status in ACTIVE for row in rows):
        return
    failed = [
        row for row in rows if row.status == "failed" or row.metrics.get("failed", 0)
    ]
    run.status = (
        "failed"
        if not rows
        or any(row.stage == Stage.INGEST and row.status == "failed" for row in rows)
        else "partial"
        if failed
        else "completed"
    )
    run.summary = {
        status: sum(row.status == status for row in rows) for status in TERMINAL
    }
    run.summary["stages_with_failures"] = len(failed)
    run.finished_at = datetime.now(UTC)
    run.failure_reason = "One or more stages reported failures" if failed else None


def finish_stage(engine: Engine, stage_id: int, attempt: int, outcome: Outcome) -> bool:
    if outcome.status not in TERMINAL:
        raise ValueError("Invalid terminal stage status")
    metrics = validate_metrics(outcome.metrics)
    reason = Reason(outcome.reason) if outcome.reason else None
    with Session(engine) as session, session.begin():
        row, run = lock_rows(session, stage_id)
        if (
            run.status not in ACTIVE
            or row.status != "running"
            or row.attempt != attempt
        ):
            return False
        for child in outcome.children:
            session.add(stage_row(run.id, child, row.id))
        row.status, row.metrics, row.failure_reason = outcome.status, metrics, reason
        row.finished_at = datetime.now(UTC)
        finalize(session, run)
        return True


def retry_stage(engine: Engine, stage_id: int, attempt: int, reason: Reason) -> bool:
    with Session(engine) as session, session.begin():
        row, run = lock_rows(session, stage_id)
        if (
            run.status not in ACTIVE
            or row.status != "running"
            or row.attempt != attempt
            or attempt >= 4
        ):
            return False
        row.status, row.failure_reason = "queued", Reason(reason)
        return True


def publication_failed(engine: Engine, stage_id: int) -> None:
    with Session(engine) as session, session.begin():
        row, run = lock_rows(session, stage_id)
        # A broker acknowledgement may be lost after a worker already claimed it.
        if run.status in ACTIVE and row.status == "queued":
            row.status, row.failure_reason = "failed", Reason.PUBLISH
            row.finished_at = datetime.now(UTC)
            finalize(session, run)


def queued_children(engine: Engine, run_id: int, parent_id: int | None) -> list[int]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(PipelineStageRun.id)
                .join(PipelineRun)
                .where(
                    PipelineStageRun.pipeline_run_id == run_id,
                    PipelineStageRun.parent_stage_id == parent_id,
                    PipelineStageRun.status == "queued",
                    PipelineRun.status.in_(ACTIVE),
                )
                .order_by(PipelineStageRun.id)
            )
        )


def mark_stale(engine: Engine, minutes: int, *, now: datetime | None = None) -> int:
    if minutes < 5:
        raise ValueError("Stale threshold must be at least five minutes")
    now = now or datetime.now(UTC)
    threshold = now - timedelta(minutes=minutes)
    count = 0
    with Session(engine) as session, session.begin():
        runs = session.scalars(
            select(PipelineRun).where(PipelineRun.status.in_(ACTIVE)).with_for_update()
        ).all()
        for run in runs:
            rows = session.scalars(
                select(PipelineStageRun).where(
                    PipelineStageRun.pipeline_run_id == run.id
                )
            ).all()
            timestamps = [run.created_at, run.started_at] + [
                t
                for row in rows
                for t in (row.created_at, row.started_at, row.finished_at)
            ]
            if max(utc_datetime(t) for t in timestamps if t) >= threshold:
                continue
            for row in rows:
                if row.status in ACTIVE:
                    row.status, row.failure_reason, row.finished_at = (
                        "failed",
                        Reason.STALE,
                        now,
                    )
            run.status, run.failure_reason, run.finished_at = (
                "failed",
                Reason.STALE,
                now,
            )
            run.summary = {"stale": True}
            count += 1
    return count


def run_status(
    engine: Engine, run_id: int, *, after_stage_id: int = 0, limit: int = 100
) -> dict:
    if after_stage_id < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid stage page bounds")
    with Session(engine) as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise ValueError("Run does not exist")
        stages = session.scalars(
            select(PipelineStageRun)
            .where(
                PipelineStageRun.pipeline_run_id == run_id,
                PipelineStageRun.id > after_stage_id,
            )
            .order_by(PipelineStageRun.id)
            .limit(limit)
        ).all()
        return {
            "run_id": run.id,
            "source": run.source_slug,
            "status": run.status,
            "celery_task_id": run.celery_task_id,
            "summary": run.summary,
            "failure_reason": run.failure_reason,
            "stages": [
                {
                    "id": row.id,
                    "stage": row.stage,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "status": row.status,
                    "attempt": row.attempt,
                    "metrics": row.metrics,
                    "failure_reason": row.failure_reason,
                }
                for row in stages
            ],
            "stage_display_limit": limit,
            "next_after_stage_id": stages[-1].id if len(stages) == limit else None,
        }


def recent_runs(engine: Engine, limit: int = 20) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    with Session(engine) as session:
        return [
            dict(row)
            for row in session.execute(
                select(
                    PipelineRun.id,
                    PipelineRun.source_slug,
                    PipelineRun.status,
                )
                .order_by(PipelineRun.id.desc())
                .limit(limit)
            ).mappings()
        ]
