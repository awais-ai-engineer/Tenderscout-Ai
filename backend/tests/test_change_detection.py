import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from change_fixtures import ChangeDatabaseMixin, item, output
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DocumentAnalysisChangeSet, TenderAnalysis
from app.services.change_detection import ComparisonError, compare_document
from app.services.change_rules import analysis_diff


class DocumentChangeTests(ChangeDatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tender_id = self.legacy_tender()
        self.document_id = self.add_document(self.tender_id)
        self.first_version = self.add_version(
            self.document_id, datetime(2026, 9, 1, tzinfo=UTC)
        )
        self.second_version = self.add_version(
            self.document_id, datetime(2026, 9, 2, tzinfo=UTC)
        )
        self.first = self.add_analysis(
            self.first_version, output(required_documents=[item("Signed declaration")])
        )
        self.second = self.add_analysis(
            self.second_version,
            output(
                required_documents=[
                    item("Signed declaration"),
                    item("Insurance certificate"),
                ]
            ),
        )

    def test_compare_outside_transaction_and_idempotent_reuse(self):
        before = self.snapshot(TenderAnalysis, self.first)

        def compare(old, new):
            self.assertEqual(self.transactions, 0)
            return analysis_diff(old, new)

        with patch(
            "app.services.change_detection.analysis_diff", side_effect=compare
        ) as compute:
            result = compare_document(self.engine, self.first, self.second)
            again = compare_document(self.engine, self.first, self.second)
        self.assertEqual(compute.call_count, 1)
        self.assertEqual(result.change_count, 1)
        self.assertEqual(result.changes[0]["new"]["evidence"], "Insurance certificate")
        self.assertEqual(result.change_set_id, again.change_set_id)
        self.assertTrue(again.reused)
        self.assertEqual(self.snapshot(TenderAnalysis, self.first), before)
        stored = self.snapshot(DocumentAnalysisChangeSet, result.change_set_id)
        self.assertEqual(stored["category_counts"], {"required_documents": 1})

    def test_changed_diff_version_appends(self):
        first = compare_document(self.engine, self.first, self.second)
        before = self.snapshot(DocumentAnalysisChangeSet, first.change_set_id)
        with patch("app.services.change_rules.CHANGESET_VERSION", "v2"):
            second = compare_document(self.engine, self.first, self.second)
        self.assertNotEqual(first.change_set_id, second.change_set_id)
        self.assertEqual(
            self.snapshot(DocumentAnalysisChangeSet, first.change_set_id), before
        )

    def test_failed_missing_and_drifted_analyses_are_rejected(self):
        for changes in (
            {"status": "failed"},
            {"analysis_schema_version": "v2"},
            {"provider": "other"},
            {"model": "other"},
            {"prompt_version": "v2"},
        ):
            analysis_id = self.add_analysis(self.second_version, **changes)
            with self.subTest(changes=changes), self.assertRaises(ComparisonError):
                compare_document(self.engine, self.first, analysis_id)
        with self.assertRaises(ComparisonError):
            compare_document(self.engine, self.first, 999)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(DocumentAnalysisChangeSet)
                ),
                0,
            )

    def test_same_reverse_and_cross_document_versions_are_rejected(self):
        same_version = self.add_analysis(self.first_version)
        other_document = self.add_document(self.tender_id)
        other_version = self.add_version(
            other_document, datetime(2026, 9, 3, tzinfo=UTC)
        )
        unrelated = self.add_analysis(other_version)
        for pair in (
            (self.first, self.first),
            (self.first, same_version),
            (self.second, self.first),
            (self.first, unrelated),
        ):
            with self.subTest(pair=pair), self.assertRaises(ComparisonError):
                compare_document(self.engine, *pair)

    def test_equal_download_timestamps_use_version_id_as_secondary_order(self):
        version = self.add_version(self.document_id, datetime(2026, 9, 1, tzinfo=UTC))
        later_id = self.add_analysis(version)
        self.assertFalse(compare_document(self.engine, self.first, later_id).reused)
        with self.assertRaises(ComparisonError):
            compare_document(self.engine, later_id, self.first)

    def test_identical_structured_content_across_versions_has_no_changes(self):
        old = self.add_analysis(self.first_version)
        new = self.add_analysis(self.second_version)
        result = compare_document(self.engine, old, new)
        self.assertFalse(result.has_changes)
        self.assertEqual(result.changes, [])

    def test_rechecks_identity_after_computation(self):
        def competing_writer(old, new):
            self.assertEqual(self.transactions, 0)
            with patch(
                "app.services.change_detection.analysis_diff", wraps=analysis_diff
            ):
                compare_document(self.engine, self.first, self.second)
            return analysis_diff(old, new)

        with patch(
            "app.services.change_detection.analysis_diff", side_effect=competing_writer
        ):
            result = compare_document(self.engine, self.first, self.second)
        self.assertTrue(result.reused)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(DocumentAnalysisChangeSet)
                ),
                1,
            )
