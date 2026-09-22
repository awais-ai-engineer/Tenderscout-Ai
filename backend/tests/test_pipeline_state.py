import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from pipeline_fixtures import PipelineDatabaseMixin
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, PipelineRun, PipelineStageRun
from app.services import pipeline as p


class PipelineStateTests(PipelineDatabaseMixin, unittest.TestCase):
    def test_concurrent_creation_uses_unique_constraint_sqlite_only(self):
        with TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + str(Path(directory) / "pipeline.db"))
            try:
                Base.metadata.create_all(engine)
                barrier = Barrier(2)

                def create():
                    barrier.wait(timeout=5)
                    return p.create_run(engine, "contracts-finder")

                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(lambda _: create(), range(2)))
                self.assertEqual(results[0][0], results[1][0])
                self.assertEqual(sorted(result[1] for result in results), [False, True])
            finally:
                engine.dispose()

    def test_stage_status_cursor_pages_without_losing_rows(self):
        row, run = self.child(p.Stage.ANALYSIS)
        first = p.run_status(self.engine, run.id, limit=1)
        second = p.run_status(
            self.engine, run.id, after_stage_id=first["next_after_stage_id"], limit=1
        )
        self.assertNotEqual(first["stages"][0]["id"], second["stages"][0]["id"])
        self.assertEqual(second["stages"][0]["id"], row.id)

    def test_manual_scheduled_collision_and_release(self):
        run_id, reused = p.create_run(self.engine, "contracts-finder")
        self.assertFalse(reused)
        self.assertEqual(
            p.create_run(self.engine, "contracts-finder", "scheduled"), (run_id, True)
        )
        root = p.queued_children(self.engine, run_id, None)[0]
        row, _ = p.claim_stage(self.engine, root)
        p.finish_stage(self.engine, root, row.attempt, p.Outcome())
        new_id, reused = p.create_run(self.engine, "contracts-finder", "scheduled")
        self.assertFalse(reused)
        self.assertNotEqual(new_id, run_id)
        self.assertEqual(self.snapshot(PipelineRun, new_id)["trigger"], "scheduled")

    def test_invalid_source_and_trigger_rejected(self):
        for source, trigger in (("other", "manual"), ("find-a-tender", "other")):
            with self.assertRaises(ValueError):
                p.create_run(self.engine, source, trigger)

    def test_partial_index_enforces_active_runs_even_for_direct_inserts(self):
        self.root()
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.add(
                PipelineRun(
                    source_slug="contracts-finder",
                    trigger="scheduled",
                    celery_task_id="test",
                )
            )

    def test_duplicate_claim_finish_and_stage_identity(self):
        root = self.root()
        row, run = p.claim_stage(self.engine, root)
        self.assertIsNone(p.claim_stage(self.engine, root))
        outcome = p.Outcome(children=[p.StageSpec(p.Stage.DOCUMENTS)])
        self.assertTrue(p.finish_stage(self.engine, root, row.attempt, outcome))
        self.assertFalse(p.finish_stage(self.engine, root, row.attempt, outcome))
        self.assertEqual(len(self.rows(run.id)), 2)
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.add(p.stage_row(run.id, p.StageSpec(p.Stage.DOCUMENTS)))

    def test_attempts_bounded_and_terminal_stages_cannot_retry(self):
        root = self.root()
        for attempt in range(1, 5):
            row, run = p.claim_stage(self.engine, root)
            self.assertEqual(row.attempt, attempt)
            self.assertEqual(
                p.retry_stage(self.engine, root, attempt, p.Reason.DATABASE),
                attempt < 4,
            )
        p.finish_stage(
            self.engine, root, 4, p.Outcome("failed", reason=p.Reason.DATABASE)
        )
        self.assertIsNone(p.claim_stage(self.engine, root))
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "failed")
        self.assertFalse(p.create_run(self.engine, "contracts-finder")[1])

    def test_finalization_waits_for_children_and_marks_partial(self):
        root = self.root()
        row, run = p.claim_stage(self.engine, root)
        p.finish_stage(
            self.engine,
            root,
            row.attempt,
            p.Outcome(
                children=[
                    p.StageSpec(p.Stage.ANALYSIS, "document_version", self.version_id),
                    p.StageSpec(p.Stage.INDEXING, "document_version", self.version_id),
                ]
            ),
        )
        ids = p.queued_children(self.engine, run.id, root)
        first, _ = p.claim_stage(self.engine, ids[0])
        p.finish_stage(
            self.engine,
            first.id,
            first.attempt,
            p.Outcome("failed", reason=p.Reason.AI_CONFIG),
        )
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "running")
        second, _ = p.claim_stage(self.engine, ids[1])
        p.finish_stage(self.engine, second.id, second.attempt, p.Outcome())
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "partial")

    def test_failed_counters_cannot_finalize_completed(self):
        root = self.root()
        row, run = p.claim_stage(self.engine, root)
        p.finish_stage(
            self.engine,
            root,
            row.attempt,
            p.Outcome(metrics={"failed": 1, "created": 2}),
        )
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "partial")

    def test_completed_and_skipped_stages_finalize_completed(self):
        row, run = self.child(p.Stage.ANALYSIS)
        p.finish_stage(
            self.engine,
            row.id,
            row.attempt,
            p.Outcome("skipped", reason=p.Reason.NO_WORK),
        )
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "completed")

    def test_metrics_reason_scope_and_status_validation(self):
        for metrics in (
            {"password": 1},
            {"failed": "secret"},
            {"failed": -1},
            {"failed": 10**10},
        ):
            with self.assertRaises(ValueError):
                p.validate_metrics(metrics)
        with self.assertRaises(ValueError):
            p.stage_row(1, p.StageSpec(p.Stage.DOCUMENTS, scope_ids=[1] * 501))
        root = self.root()
        row, _ = p.claim_stage(self.engine, root)
        with self.assertRaises(ValueError):
            p.finish_stage(self.engine, root, row.attempt, p.Outcome("running"))
        with self.assertRaises(ValueError):
            p.finish_stage(
                self.engine, root, row.attempt, p.Outcome("failed", reason="raw secret")
            )

    def test_stale_only_explicitly_marks_inactive_run_and_children(self):
        root = self.root()
        row, run = p.claim_stage(self.engine, root)
        now = datetime.now(UTC)
        self.assertEqual(p.mark_stale(self.engine, 60, now=now), 0)
        with Session(self.engine) as session, session.begin():
            for item in (
                session.get(PipelineRun, run.id),
                session.get(PipelineStageRun, root),
            ):
                item.created_at = item.started_at = now - timedelta(hours=2)
        self.assertEqual(p.run_status(self.engine, run.id)["status"], "running")
        self.assertEqual(p.mark_stale(self.engine, 60, now=now), 1)
        self.assertEqual(
            p.run_status(self.engine, run.id)["failure_reason"], p.Reason.STALE
        )
        self.assertFalse(p.finish_stage(self.engine, root, row.attempt, p.Outcome()))
        self.assertEqual(p.mark_stale(self.engine, 60, now=now), 0)

    def test_publication_failure_is_visible_and_delayed_delivery_cannot_execute(self):
        root = self.root()
        p.publication_failed(self.engine, root)
        self.assertIsNone(p.claim_stage(self.engine, root))
        row, run = p.load_stage(self.engine, root)
        self.assertEqual(
            (row.status, run.status, row.failure_reason),
            ("failed", "failed", p.Reason.PUBLISH),
        )

    def test_publication_uncertainty_does_not_cancel_running_work(self):
        root = self.root()
        p.claim_stage(self.engine, root)
        p.publication_failed(self.engine, root)
        self.assertEqual(p.load_stage(self.engine, root)[0].status, "running")

    def test_stage_fk_and_audit_delete_restriction(self):
        root = self.root()
        _, run = p.load_stage(self.engine, root)
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.execute(delete(PipelineRun).where(PipelineRun.id == run.id))
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.add(p.stage_row(9999, p.StageSpec(p.Stage.INGEST)))

    def test_recent_is_bounded_and_safe(self):
        self.root()
        self.assertEqual(len(p.recent_runs(self.engine, 1)), 1)
        with self.assertRaises(ValueError):
            p.recent_runs(self.engine, 101)
        with self.assertRaises(ValueError):
            p.run_status(self.engine, 9999)
