import json
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import Mock, patch

import httpx
from pipeline_fixtures import PipelineDatabaseMixin
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, ProviderFailure
from app.models import Source, Tender
from app.pipeline import main
from app.scrapers import contracts_finder, find_tender
from app.scrapers.errors import SourceFetchError, TransientSourceFetchError
from app.scrapers.records import DiscoveredDocument, DiscoveredDocuments, ParsedListing
from app.services import pipeline as p
from app.services import pipeline_steps as steps
from app.services.documents import DocumentResult
from app.worker import tasks
from app.worker.celery_app import celery_app


class WorkerTaskTests(PipelineDatabaseMixin, unittest.TestCase):
    def test_real_service_eager_pipeline_and_repeat_without_extra_provider_calls(self):
        record = DiscoveredDocument(
            tender_external_id=self.record.external_id,
            source_url="https://example.test/a.pdf",
        )

        def processing(engine, client, records, settings):
            self.assertEqual(self.transactions, 0)
            with Session(engine) as session:
                tender_id = session.scalar(
                    select(Tender.id)
                    .join(Source)
                    .where(Source.slug == "contracts-finder")
                )
            if not hasattr(self, "pipeline_document"):
                self.pipeline_document = self.add_document(tender_id)
                self.add_version(self.pipeline_document, datetime.now(UTC))
                return DocumentResult(discovered=1, versions_created=1, extracted=1)
            return DocumentResult(discovered=1, content_unchanged=1)

        with (
            patch.object(contracts_finder, "fetch_releases", return_value={}),
            patch.object(
                contracts_finder,
                "parse_releases",
                return_value=ParsedListing([self.record]),
            ),
            patch.object(
                steps, "discover_documents", return_value=DiscoveredDocuments([record])
            ),
            patch.object(steps, "process_documents", side_effect=processing),
            patch.object(steps, "OpenAIStructuredClient", return_value=self.structured),
            patch.object(steps, "OpenAIEmbeddingClient", return_value=self.embedder),
        ):
            first = tasks.trigger_pipeline(self.engine, "contracts-finder")
            second = tasks.trigger_pipeline(self.engine, "contracts-finder")
        self.assertEqual(
            (first["status"], second["status"]), ("completed", "completed")
        )
        self.assertEqual(
            [row.stage for row in self.rows(first["run_id"])],
            ["ingest", "documents", "analysis", "indexing", "matching", "changes"],
        )
        self.assertEqual(
            [row.stage for row in self.rows(second["run_id"])], ["ingest", "documents"]
        )
        self.assertEqual(self.structured.calls, 1)
        self.assertEqual(len(self.embedder.calls), 1)

    def test_source_timeout_subtype_but_403_not_retryable(self):
        for fetch in (find_tender.fetch_listing, contracts_finder.fetch_releases):
            client = Mock(spec=httpx.Client)
            client.get.side_effect = httpx.ReadTimeout("sensitive transport")
            with self.assertRaises(TransientSourceFetchError) as caught:
                fetch(client)
            self.assertTrue(tasks.failure_kind(caught.exception)[1])
            self.assertNotIn("sensitive", str(caught.exception))
            client.get.side_effect = None
            client.get.return_value = httpx.Response(
                403, request=httpx.Request("GET", "https://example.test")
            )
            with self.assertRaises(SourceFetchError) as caught:
                fetch(client)
            self.assertFalse(tasks.failure_kind(caught.exception)[1])

    def setUp(self):
        super().setUp()
        previous = {
            name: getattr(celery_app.conf, name)
            for name in ("task_always_eager", "broker_url", "result_backend")
        }
        self.addCleanup(celery_app.conf.update, previous)
        celery_app.conf.update(
            task_always_eager=True, broker_url="memory://", result_backend=None
        )
        for target, value in (
            ("app.worker.tasks.get_engine", self.engine),
            ("app.worker.tasks.Settings", self.settings),
        ):
            mocked = patch(target, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_eager_pipeline_records_skipped_stages_and_duplicate_delivery_is_safe(self):
        calls = []

        def step(engine, row, run, settings):
            self.assertEqual(self.transactions, 0)
            calls.append(row.stage)
            if row.stage == p.Stage.INGEST:
                return p.Outcome(children=[p.StageSpec(p.Stage.DOCUMENTS)])
            return p.Outcome("skipped", reason=p.Reason.UNSUPPORTED)

        with patch.object(tasks, "execute_stage", side_effect=step):
            result = tasks.trigger_pipeline(self.engine, "find-a-tender")
            root = self.rows(result["run_id"])[0].id
            duplicate = tasks.ingest_source_task.apply(args=[root]).get()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(calls, [p.Stage.INGEST, p.Stage.DOCUMENTS])
        self.assertEqual([row.attempt for row in self.rows(result["run_id"])], [1, 1])

    def test_duplicate_while_running_does_not_execute_provider_again(self):
        root = self.root()

        def step(*args):
            duplicate = tasks.ingest_source_task.apply(args=[root]).get()
            self.assertTrue(duplicate["duplicate"])
            return p.Outcome()

        with patch.object(tasks, "execute_stage", side_effect=step) as execute:
            self.assertTrue(tasks.ingest_source_task.apply(args=[root]).successful())
        execute.assert_called_once()

    def test_analysis_failure_does_not_block_indexing_or_finalize_success(self):
        calls = []

        def step(engine, row, run, settings):
            calls.append(row.stage)
            if row.stage == p.Stage.INGEST:
                return p.Outcome(
                    children=[
                        p.StageSpec(
                            p.Stage.ANALYSIS, "document_version", self.version_id
                        ),
                        p.StageSpec(
                            p.Stage.INDEXING, "document_version", self.version_id
                        ),
                    ]
                )
            if row.stage == p.Stage.ANALYSIS:
                return p.Outcome("failed", reason=p.Reason.ANALYSIS_FAILED)
            return p.Outcome(metrics={"embeddings_created": 1})

        with patch.object(tasks, "execute_stage", side_effect=step):
            result = tasks.trigger_pipeline(self.engine, "contracts-finder")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(calls, [p.Stage.INGEST, p.Stage.ANALYSIS, p.Stage.INDEXING])

    def test_transient_retry_is_bounded_to_four_attempts_and_sanitized(self):
        root = self.root()
        exc = OperationalError("secret SQL", {}, Exception("secret password"))
        with patch.object(tasks, "execute_stage", side_effect=exc) as execute:
            result = tasks.ingest_source_task.apply(args=[root])
        row, run = p.load_stage(self.engine, root)
        self.assertFalse(result.successful())
        self.assertEqual(
            (row.attempt, execute.call_count, row.status, run.status),
            (4, 4, "failed", "failed"),
        )
        self.assertNotIn("secret", str(result.result))
        self.assertEqual(row.failure_reason, p.Reason.DATABASE)

    def test_nontransient_failure_no_retry_and_no_raw_error(self):
        root = self.root()
        with patch.object(
            tasks, "execute_stage", side_effect=ValueError("secret content")
        ) as execute:
            result = tasks.ingest_source_task.apply(args=[root])
        self.assertFalse(result.successful())
        execute.assert_called_once()
        self.assertNotIn("secret", str(result.result))
        self.assertEqual(p.load_stage(self.engine, root)[1].status, "failed")

    def test_retry_classifier_excludes_source_access_and_schema_failures(self):
        for exc in (
            ValueError(),
            SourceFetchError(),
            ProviderError(ProviderFailure.INVALID_OUTPUT),
            ProviderError(ProviderFailure.API),
        ):
            self.assertFalse(tasks.failure_kind(exc)[1])
        for exc in (
            httpx.ConnectError("test"),
            httpx.ReadTimeout("test"),
            ProviderError(ProviderFailure.TIMEOUT),
            ProviderError(ProviderFailure.CONNECTION),
        ):
            self.assertTrue(tasks.failure_kind(exc)[1])

    def test_broker_failure_marks_audit_failed_and_manual_scheduled_share_path(self):
        with (
            patch.object(
                tasks.ingest_source_task,
                "apply_async",
                side_effect=RuntimeError("redis://secret"),
            ),
            self.assertLogs(tasks.logger) as logs,
        ):
            result = tasks.trigger_pipeline(self.engine, "contracts-finder")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("secret", " ".join(logs.output))
        with patch.object(
            tasks, "trigger_pipeline", return_value={"status": "queued"}
        ) as trigger:
            tasks.trigger_source_task.apply(args=["contracts-finder"]).get()
        trigger.assert_called_once_with(self.engine, "contracts-finder", "scheduled")

    def test_active_trigger_does_not_publish_second_root(self):
        with patch.object(tasks.ingest_source_task, "apply_async") as publish:
            first = tasks.trigger_pipeline(self.engine, "contracts-finder")
            second = tasks.trigger_pipeline(
                self.engine, "contracts-finder", "scheduled"
            )
        publish.assert_called_once()
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(
            publish.call_args.kwargs["args"], [self.rows(first["run_id"])[0].id]
        )

    def test_operational_cli_run_status_recent_and_stale(self):
        with (
            patch("app.pipeline.create_database_engine", return_value=self.engine),
            patch.object(self.engine, "dispose"),
            patch("app.pipeline.Settings", return_value=self.settings),
            patch.object(tasks.ingest_source_task, "apply_async") as publish,
        ):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["run", "--source", "contracts-finder"]), 0)
            run = json.loads(output.getvalue())
            publish.assert_called_once()
            for command in (
                ["status", "--run-id", str(run["run_id"])],
                ["recent", "--limit", "1"],
                ["mark-stale"],
            ):
                with redirect_stdout(StringIO()):
                    self.assertEqual(main(command), 0)
            with (
                self.assertLogs("app.pipeline", level="ERROR"),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(main(["recent", "--limit", "101"]), 1)
