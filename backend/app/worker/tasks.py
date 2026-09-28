import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, ProviderFailure
from app.core.config import Settings
from app.models import Alert, NotificationPreference
from app.scrapers.errors import (
    SourceFetchError,
    SourceParseError,
    TransientSourceFetchError,
)
from app.services import pipeline
from app.services.notifications import (
    deliver_alert,
    generate_deadline_alerts,
    send_digests,
)
from app.services.pipeline_steps import execute_stage
from app.worker.celery_app import celery_app
from app.worker.runtime import get_engine

logger = logging.getLogger(__name__)


class StageExecutionError(RuntimeError):
    """Only fixed, sanitized messages cross the Celery error boundary."""


class TransientStageError(StageExecutionError):
    pass


def failure_kind(exc: Exception) -> tuple[pipeline.Reason, bool]:
    if isinstance(exc, OperationalError):
        return pipeline.Reason.DATABASE, True
    if isinstance(exc, SQLAlchemyError):
        return pipeline.Reason.DATABASE, False
    if isinstance(exc, ProviderError):
        return pipeline.Reason.PROVIDER, exc.reason in {
            ProviderFailure.TIMEOUT,
            ProviderFailure.CONNECTION,
        }
    if isinstance(
        exc, (httpx.TimeoutException, httpx.ConnectError, TransientSourceFetchError)
    ):
        return pipeline.Reason.SOURCE, True
    if isinstance(exc, (SourceFetchError, SourceParseError)):
        # HTTP statuses, including 403, are deliberately not retried.
        return pipeline.Reason.SOURCE, False
    if isinstance(exc, ValueError):
        return pipeline.Reason.INVALID, False
    return pipeline.Reason.UNEXPECTED, False


def publish_stage(engine, stage_id: int) -> bool:
    row, run = pipeline.load_stage(engine, stage_id)
    task = TASKS[pipeline.Stage(row.stage)]
    task_id = (
        run.celery_task_id
        if row.stage == pipeline.Stage.INGEST
        else f"stage-{stage_id}"
    )
    try:
        task.apply_async(args=[stage_id], task_id=task_id)
        return True
    except Exception:
        pipeline.publication_failed(engine, stage_id)
        logger.error(
            "event=pipeline_publish_failed run_id=%s stage_id=%s", run.id, stage_id
        )
        return False


def dispatch_children(engine, run_id: int, parent_id: int | None) -> None:
    for stage_id in pipeline.queued_children(engine, run_id, parent_id):
        publish_stage(engine, stage_id)


def trigger_pipeline(engine, source: str, trigger: str = "manual") -> dict:
    run_id, reused = pipeline.create_run(engine, source, trigger)
    if not reused:
        dispatch_children(engine, run_id, None)
    result = pipeline.run_status(engine, run_id)
    return {
        key: result[key] for key in ("run_id", "source", "status", "celery_task_id")
    } | {"reused": reused}


def perform(task, stage_id: int, expected: pipeline.Stage):
    engine = get_engine()
    row = None
    try:
        candidate, _ = pipeline.load_stage(engine, stage_id)
        if candidate.stage != expected:
            raise ValueError("Task stage mismatch")
        claimed = pipeline.claim_stage(engine, stage_id)
        if claimed is None:
            if candidate.status in pipeline.TERMINAL:
                dispatch_children(engine, candidate.pipeline_run_id, stage_id)
            return {"stage_id": stage_id, "duplicate": True}
        row, run = claimed
        try:
            outcome = execute_stage(engine, row, run, Settings())
        except Exception as exc:
            reason, transient = failure_kind(exc)
            if (
                transient
                and task.request.retries < 3
                and pipeline.retry_stage(engine, stage_id, row.attempt, reason)
            ):
                raise TransientStageError(reason.value) from None
            outcome = pipeline.Outcome("failed", reason=reason)
        saved = pipeline.finish_stage(engine, stage_id, row.attempt, outcome)
        if not saved:
            return {"stage_id": stage_id, "status": "ignored_after_finalization"}
        dispatch_children(engine, run.id, stage_id)
        logger.info(
            "event=pipeline_stage run_id=%s stage=%s "
            "entity_type=%s entity_id=%s status=%s",
            run.id,
            row.stage,
            row.entity_type,
            row.entity_id,
            outcome.status,
        )
        if outcome.status == "failed":
            raise StageExecutionError(
                outcome.reason.value if outcome.reason else "Stage failed"
            )
        return {"stage_id": stage_id, "status": outcome.status}
    except TransientStageError:
        raise
    except StageExecutionError:
        raise
    except Exception as exc:
        reason, transient = failure_kind(exc)
        # A DB outage may prevent even claiming or recording a failure; maintenance
        # will expose an unfinalized row. No raw SQL/connection exception is logged.
        if transient and task.request.retries < 3:
            if row is not None:
                try:
                    pipeline.retry_stage(engine, stage_id, row.attempt, reason)
                except SQLAlchemyError:
                    logger.error(
                        "event=pipeline_retry_audit_unavailable stage_id=%s", stage_id
                    )
            raise TransientStageError(reason.value) from None
        if row is not None:
            try:
                pipeline.finish_stage(
                    engine,
                    stage_id,
                    row.attempt,
                    pipeline.Outcome("failed", reason=reason),
                )
            except SQLAlchemyError:
                logger.error("event=pipeline_audit_unavailable stage_id=%s", stage_id)
        raise StageExecutionError(reason.value) from None


OPTIONS = dict(
    bind=True,
    autoretry_for=(TransientStageError,),
    retry_backoff=30,
    retry_backoff_max=180,
    retry_jitter=True,
    max_retries=3,
)


@celery_app.task(**OPTIONS)
def ingest_source_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.INGEST)


@celery_app.task(**OPTIONS)
def process_documents_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.DOCUMENTS)


@celery_app.task(**OPTIONS)
def analyze_document_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.ANALYSIS)


@celery_app.task(**OPTIONS)
def index_document_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.INDEXING)


@celery_app.task(**OPTIONS)
def match_analysis_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.MATCHING)


@celery_app.task(**OPTIONS)
def compare_analysis_task(self, stage_id: int):
    return perform(self, stage_id, pipeline.Stage.CHANGES)


@celery_app.task(**OPTIONS)
def trigger_source_task(self, source_slug: str):
    try:
        return trigger_pipeline(get_engine(), source_slug, "scheduled")
    except OperationalError:
        raise TransientStageError(pipeline.Reason.DATABASE.value) from None
    except Exception:
        raise StageExecutionError("Pipeline trigger failed") from None


@celery_app.task(bind=True, max_retries=3, retry_backoff=30, retry_jitter=True)
def deliver_alert_task(self, alert_id: int):
    try:
        return {"sent": deliver_alert(get_engine(), alert_id, Settings())}
    except RuntimeError:
        raise self.retry(exc=StageExecutionError("Email delivery failed")) from None


@celery_app.task
def send_daily_digests_task():
    return {"digests_sent": send_digests(get_engine(), Settings())}


@celery_app.task
def generate_deadline_reminders_task():
    settings = Settings()
    ids = generate_deadline_alerts(get_engine(), settings)
    for alert_id in ids:
        deliver_alert_task.apply_async(args=[alert_id], task_id=f"alert-{alert_id}")
    return {"alerts_created": len(ids)}


@celery_app.task
def retry_instant_alerts_task():
    with Session(get_engine()) as session:
        ids = list(
            session.scalars(
                select(Alert.id)
                .join(
                    NotificationPreference,
                    NotificationPreference.company_id == Alert.company_id,
                )
                .where(
                    NotificationPreference.email_enabled.is_(True),
                    NotificationPreference.delivery_mode == "instant",
                    Alert.delivery_status.in_(("pending", "unconfigured")),
                )
                .order_by(Alert.id)
                .limit(100)
            )
        )
    for alert_id in ids:
        deliver_alert_task.apply_async(args=[alert_id], task_id=f"alert-{alert_id}")
    return {"queued": len(ids)}


TASKS = {
    pipeline.Stage.INGEST: ingest_source_task,
    pipeline.Stage.DOCUMENTS: process_documents_task,
    pipeline.Stage.ANALYSIS: analyze_document_task,
    pipeline.Stage.INDEXING: index_document_task,
    pipeline.Stage.MATCHING: match_analysis_task,
    pipeline.Stage.CHANGES: compare_analysis_task,
}
