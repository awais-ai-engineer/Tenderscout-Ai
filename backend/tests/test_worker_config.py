import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from app.core.config import Settings
from app.worker import runtime
from app.worker.celery_app import TASK_PREFIX, celery_config, create_celery


class WorkerConfigTests(unittest.TestCase):
    def settings(self, **values):
        with patch.dict(os.environ, {}, clear=True):
            return Settings(_env_file=None, postgres_password="test-only", **values)

    def test_json_queues_delivery_prefetch_and_no_result_backend(self):
        config = celery_config(self.settings())
        self.assertEqual(config["accept_content"], ["json"])
        self.assertEqual(config["result_accept_content"], ["json"])
        self.assertEqual(config["task_serializer"], "json")
        self.assertEqual(config["result_serializer"], "json")
        self.assertEqual(
            {q.name for q in config["task_queues"]},
            {"ingestion", "documents", "ai", "default"},
        )
        self.assertEqual(
            config["task_routes"][TASK_PREFIX + "analyze_document_task"],
            {"queue": "ai"},
        )
        self.assertEqual(
            config["task_routes"][TASK_PREFIX + "process_documents_task"],
            {"queue": "documents"},
        )
        self.assertTrue(config["task_acks_late"])
        self.assertFalse(config["task_reject_on_worker_lost"])
        self.assertEqual(config["worker_prefetch_multiplier"], 1)
        self.assertIsNone(config["result_backend"])
        self.assertTrue(config["task_ignore_result"])
        self.assertFalse(config["task_always_eager"])

    def test_escaped_redis_password_and_secret_overrides(self):
        password = "test@:/?#%"
        settings = self.settings(redis_password=password, redis_host="::1", redis_db=2)
        url = urlsplit(celery_config(settings)["broker_url"])
        self.assertEqual(unquote(url.password), password)
        self.assertEqual((url.hostname, url.path), ("::1", "/2"))
        secret_url = "rediss://:test-only@localhost:6380/3"
        overridden = self.settings(
            celery_broker_url=secret_url, celery_result_backend=secret_url
        )
        self.assertEqual(celery_config(overridden)["broker_url"], secret_url)
        self.assertEqual(celery_config(overridden)["result_backend"], secret_url)
        for rendering in (repr(overridden), overridden.model_dump_json()):
            self.assertNotIn(secret_url, rendering)
        self.assertNotIn(password, repr(settings))

    def test_registry_driven_schedules_and_minimum_interval(self):
        config = celery_config(self.settings(find_a_tender_schedule_minutes=0))
        self.assertEqual(
            set(config["beat_schedule"]),
            {
                "contracts-finder",
                "ted",
                "deadline-reminders",
                "daily-digests",
                "instant-alert-recovery",
            },
        )
        self.assertEqual(
            config["beat_schedule"]["contracts-finder"]["schedule"].total_seconds(),
            900,
        )
        self.assertEqual(
            config["beat_schedule"]["ted"]["schedule"].total_seconds(), 1800
        )
        self.assertEqual(
            config["beat_schedule"]["contracts-finder"]["task"],
            TASK_PREFIX + "trigger_source_task",
        )
        self.assertEqual(
            celery_config(
                self.settings(
                    find_a_tender_schedule_minutes=0,
                    contracts_finder_schedule_minutes=0,
                    ted_schedule_minutes=0,
                )
            )["beat_schedule"],
            {
                "deadline-reminders": config["beat_schedule"]["deadline-reminders"],
                "daily-digests": config["beat_schedule"]["daily-digests"],
                "instant-alert-recovery": config["beat_schedule"][
                    "instant-alert-recovery"
                ],
            },
        )
        for values in (
            {"find_a_tender_schedule_minutes": 1},
            {"auto_match_max_companies": 0},
            {"pipeline_max_tenders": 501},
            {"celery_broker_url": "amqp://localhost"},
        ):
            with self.assertRaises(ValidationError):
                self.settings(**values)

    def test_app_boots_without_ai_and_eager_requires_opt_in(self):
        with (
            patch(
                "socket.socket.connect", side_effect=AssertionError("No broker allowed")
            ),
            patch("app.ai.openai_client.OpenAIStructuredClient") as client,
        ):
            app = create_celery(self.settings(celery_task_always_eager=True))
            self.addCleanup(app.close)
            self.assertTrue(app.conf.task_always_eager)
            self.assertIsNone(self.settings().openai_api_key)
        client.assert_not_called()

    def test_engine_lazy_reused_and_fork_disposes_inherited_pool(self):
        old_engine, old_pid = runtime._engine, runtime._pid
        self.addCleanup(setattr, runtime, "_engine", old_engine)
        self.addCleanup(setattr, runtime, "_pid", old_pid)
        runtime._engine, runtime._pid = None, None
        first, second = Mock(), Mock()
        with (
            patch.object(runtime, "Settings", return_value=self.settings()),
            patch.object(
                runtime, "create_database_engine", side_effect=[first, second]
            ) as factory,
            patch.object(runtime.os, "getpid", return_value=10) as pid,
        ):
            self.assertIs(runtime.get_engine(), first)
            self.assertIs(runtime.get_engine(), first)
            self.assertEqual(factory.call_count, 1)
            pid.return_value = 11
            self.assertIs(runtime.get_engine(), second)
            first.dispose.assert_called_once_with(close=False)
            runtime.shutdown()
            second.dispose.assert_called_once_with()
            self.assertIsNone(runtime._engine)
