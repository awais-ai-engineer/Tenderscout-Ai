import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from change_fixtures import ChangeDatabaseMixin
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tender, TenderMetadataChangeSet, TenderRevision
from app.scrapers.records import ParsedListing, ScrapedTender
from app.services.change_detection import ComparisonError, compare_metadata
from app.services.change_rules import metadata_diff
from app.services.ingestion import ingest_tenders
from app.services.revisions import revision_history


class RevisionTests(ChangeDatabaseMixin, unittest.TestCase):
    def ingest(self, record=None):
        return ingest_tenders(
            self.engine, self.source, ParsedListing([record or self.record])
        )

    def revisions(self):
        with Session(self.engine) as session:
            return [
                {
                    column.name: getattr(row, column.name)
                    for column in TenderRevision.__table__.c
                }
                for row in session.scalars(
                    select(TenderRevision).order_by(TenderRevision.id)
                )
            ]

    def count(self, model):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(model))

    def test_new_unchanged_last_seen_and_metrics(self):
        with patch("app.services.ingestion.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 20, tzinfo=UTC)
            first = self.ingest()
            before = self.revisions()[0]
            clock.now.return_value = datetime(2026, 9, 21, tzinfo=UTC)
            second = self.ingest()
        self.assertEqual((first.created, first.changed, first.unchanged), (1, 0, 0))
        self.assertEqual((second.created, second.changed, second.unchanged), (0, 0, 1))
        self.assertEqual(self.revisions(), [before])
        self.assertEqual(before["revision_index"], 1)
        self.assertEqual(self.count(TenderMetadataChangeSet), 0)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(Tender.last_seen_at)).day, 21)

    def test_a_b_a_preserves_three_revisions_and_auto_changes(self):
        self.ingest()
        before = self.revisions()[0]
        self.assertEqual(
            self.ingest(self.record.model_copy(update={"title": "B"})).changed, 1
        )
        self.assertEqual(self.ingest().changed, 1)
        rows = self.revisions()
        self.assertEqual([row["revision_index"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0], before)
        self.assertEqual(rows[0]["snapshot_hash"], rows[2]["snapshot_hash"])
        self.assertEqual(self.count(TenderMetadataChangeSet), 2)
        result = compare_metadata(self.engine, rows[0]["id"], rows[2]["id"])
        self.assertFalse(result.has_changes)
        self.assertEqual(result.change_count, 0)

    def test_sparse_update_preserves_complete_resulting_snapshot(self):
        self.ingest()
        sparse = ScrapedTender(
            title=self.record.title,
            source_url=self.record.source_url,
            deadline=datetime(2026, 10, 17, tzinfo=UTC),
        )
        self.assertEqual(self.ingest(sparse).changed, 1)
        rows = self.revisions()
        self.assertEqual(rows[-1]["organization"], "Authority A")
        self.assertEqual(rows[-1]["external_id"], self.record.external_id)
        self.assertEqual(rows[-1]["deadline"].day, 17)
        with Session(self.engine) as session:
            changes = session.scalar(select(TenderMetadataChangeSet))
            self.assertEqual(changes.changed_fields, ["deadline"])

    def test_legacy_unchanged_records_only_stored_baseline(self):
        tender_id = self.legacy_tender(content_hash="a" * 64)
        self.assertEqual(self.count(TenderRevision), 0)
        self.assertEqual(self.ingest().unchanged, 1)
        rows = self.revisions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tender_id"], tender_id)
        self.assertEqual(
            rows[0]["observed_at"].replace(tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)
        )
        self.assertEqual(rows[0]["source_content_hash"], "a" * 64)
        self.assertEqual(self.count(TenderMetadataChangeSet), 0)

    def test_legacy_changed_captures_pre_update_baseline_then_revision_two(self):
        self.legacy_tender()
        now = datetime(2026, 9, 21, tzinfo=UTC)
        with patch("app.services.ingestion.datetime") as clock:
            clock.now.return_value = now
            self.assertEqual(
                self.ingest(
                    self.record.model_copy(update={"title": "Changed"})
                ).changed,
                1,
            )
        rows = self.revisions()
        self.assertEqual([row["title"] for row in rows], [self.record.title, "Changed"])
        self.assertEqual(rows[1]["observed_at"].replace(tzinfo=UTC), now)
        self.assertEqual(self.count(TenderMetadataChangeSet), 1)

    def test_same_batch_duplicate_does_not_duplicate_revision(self):
        result = ingest_tenders(
            self.engine, self.source, ParsedListing([self.record, self.record])
        )
        self.assertEqual((result.created, result.unchanged), (1, 1))
        self.assertEqual(self.count(TenderRevision), 1)

    def test_revision_and_changeset_failure_rolls_back_current_tender(self):
        self.ingest()
        before = self.revisions()[0]
        for table in ("tender_revisions", "tender_metadata_change_sets"):

            def fail(connection, cursor, statement, parameters, context, executemany):
                if statement.startswith(f"INSERT INTO {table}"):
                    raise IntegrityError("synthetic", {}, Exception("synthetic"))

            event.listen(self.engine, "before_cursor_execute", fail)
            try:
                with (
                    self.assertLogs("app.services.ingestion", level="ERROR"),
                    self.assertRaises(IntegrityError),
                ):
                    self.ingest(self.record.model_copy(update={"title": "Changed"}))
            finally:
                event.remove(self.engine, "before_cursor_execute", fail)
            self.assertEqual(self.revisions(), [before])
            with Session(self.engine) as session:
                self.assertEqual(
                    session.scalar(select(Tender.title)), self.record.title
                )

    def test_metadata_reuses_auto_diff_and_version_bump_preserves_history(self):
        self.ingest()
        self.ingest(self.record.model_copy(update={"title": "Changed"}))
        first, second = self.revisions()
        result = compare_metadata(self.engine, first["id"], second["id"])
        self.assertTrue(result.reused)
        before = self.snapshot(TenderMetadataChangeSet, result.change_set_id)

        def compare(old, new):
            self.assertEqual(self.transactions, 0)
            return metadata_diff(old, new)

        with (
            patch("app.services.change_rules.CHANGESET_VERSION", "v2"),
            patch("app.services.change_detection.metadata_diff", side_effect=compare),
        ):
            changed = compare_metadata(self.engine, first["id"], second["id"])
            reused = compare_metadata(self.engine, first["id"], second["id"])
        self.assertNotEqual(result.change_set_id, changed.change_set_id)
        self.assertTrue(reused.reused)
        self.assertEqual(
            before, self.snapshot(TenderMetadataChangeSet, result.change_set_id)
        )

    def test_invalid_metadata_pairs_and_history_bounds(self):
        self.ingest()
        self.ingest(self.record.model_copy(update={"title": "B"}))
        first, second = self.revisions()
        other = ScrapedTender.model_validate(
            self.record.model_dump()
            | {"external_id": "other", "source_url": "https://example.test/other"}
        )
        self.ingest(other)
        third = self.revisions()[-1]
        for pair in (
            (first["id"], first["id"]),
            (second["id"], first["id"]),
            (first["id"], third["id"]),
            (first["id"], 999),
        ):
            with self.assertRaises(ComparisonError):
                compare_metadata(self.engine, *pair)
        history = revision_history(self.engine, first["tender_id"], limit=1)
        self.assertEqual(len(history), 1)
        self.assertNotIn("description", history[0])
        self.assertEqual(
            revision_history(self.engine, first["tender_id"], after_index=1)[0][
                "revision_index"
            ],
            2,
        )
