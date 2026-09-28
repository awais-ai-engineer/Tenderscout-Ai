import logging
from datetime import timedelta
from urllib.parse import quote

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import Settings
from app.sources import SOURCE_CONNECTORS

TASK_PREFIX = "app.worker.tasks."
ROUTES = {
    "ingest_source_task": "ingestion",
    "process_documents_task": "documents",
    "analyze_document_task": "ai",
    "index_document_task": "ai",
    "match_analysis_task": "default",
    "compare_analysis_task": "default",
    "trigger_source_task": "default",
    "deliver_alert_task": "default",
    "send_daily_digests_task": "default",
    "generate_deadline_reminders_task": "default",
    "retry_instant_alerts_task": "default",
}


def celery_config(settings: Settings) -> dict:
    host = settings.redis_host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    auth = (
        f":{quote(settings.redis_password.get_secret_value(), safe='')}@"
        if settings.redis_password
        else ""
    )
    broker = (
        settings.celery_broker_url.get_secret_value()
        if settings.celery_broker_url
        else f"redis://{auth}{host}:{settings.redis_port}/{settings.redis_db}"
    )
    schedules = {}
    for source in SOURCE_CONNECTORS:
        minutes = getattr(settings, source.replace("-", "_") + "_schedule_minutes")
        if minutes:
            schedules[source] = {
                "task": TASK_PREFIX + "trigger_source_task",
                "schedule": timedelta(minutes=minutes),
                "args": [source],
            }
    schedules["deadline-reminders"] = {
        "task": TASK_PREFIX + "generate_deadline_reminders_task",
        "schedule": crontab(hour=6, minute=0),
    }
    schedules["daily-digests"] = {
        "task": TASK_PREFIX + "send_daily_digests_task",
        "schedule": crontab(hour=settings.daily_digest_hour_utc, minute=0),
    }
    schedules["instant-alert-recovery"] = {
        "task": TASK_PREFIX + "retry_instant_alerts_task",
        "schedule": timedelta(minutes=15),
    }
    return dict(
        broker_url=broker,
        result_backend=settings.celery_result_backend.get_secret_value()
        if settings.celery_result_backend
        else None,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        task_default_queue="default",
        task_queues=tuple(
            Queue(name) for name in ("ingestion", "documents", "ai", "default")
        ),
        task_routes={
            TASK_PREFIX + name: {"queue": queue} for name, queue in ROUTES.items()
        },
        task_create_missing_queues=False,
        task_acks_late=True,
        task_acks_on_failure_or_timeout=True,
        task_reject_on_worker_lost=False,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=3,
        broker_connection_timeout=5,
        broker_transport_options={
            "visibility_timeout": 21600,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
        },
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 1,
            "interval_max": 3,
        },
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=False,
        task_store_eager_result=False,
        enable_utc=True,
        timezone="UTC",
        beat_schedule=schedules,
        worker_hijack_root_logger=False,
    )


def create_celery(settings: Settings | None = None) -> Celery:
    app = Celery("tenderscout", include=["app.worker.tasks"])
    app.add_defaults(lambda: celery_config(settings or Settings()))
    return app


for name in ("openai", "httpx", "httpx2"):
    logging.getLogger(name).setLevel(logging.WARNING)

celery_app = create_celery()
