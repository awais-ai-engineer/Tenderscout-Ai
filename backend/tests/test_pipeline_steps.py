import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pipeline_fixtures import PipelineDatabaseMixin
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, ProviderFailure
from app.models import CompanyProfile, DocumentVersion, TenderRevision
from app.scrapers import contracts_finder, find_tender
from app.scrapers.records import DiscoveredDocument, DiscoveredDocuments, ParsedListing
from app.services import pipeline as p
from app.services import pipeline_steps as steps
from app.services.documents import DocumentResult
from app.services.ingestion import ingest_tenders


class PipelineStepTests(PipelineDatabaseMixin, unittest.TestCase):
    def test_invalid_company_does_not_block_other_companies(self):
        analysis_id = self.add_analysis(self.version_id)
        row, run = self.child(p.Stage.MATCHING, "analysis", analysis_id)
        with Session(self.engine) as session, session.begin():
            session.add_all([CompanyProfile(name="One"), CompanyProfile(name="Two")])
        self.settings.auto_match_enabled = True
        with patch.object(
            steps,
            "match_tender",
            side_effect=[
                ValueError("invalid private data"),
                SimpleNamespace(reused=False),
            ],
        ) as match:
            outcome = steps.matching_step(self.engine, row, run, self.settings)
        self.assertEqual(
            (outcome.status, outcome.metrics["failed"], outcome.metrics["matched"]),
            ("failed", 1, 1),
        )
        self.assertEqual(match.call_count, 2)
        self.assertNotIn("private", str(outcome))

    def test_ingestion_uses_real_service_revisions_and_exact_affected_scope(self):
        root = self.root("find-a-tender")
        row, run = p.claim_stage(self.engine, root)
        with (
            patch.object(
                find_tender,
                "fetch_listing",
                side_effect=lambda client: self.assertEqual(self.transactions, 0),
            ),
            patch.object(
                find_tender, "parse_listing", return_value=ParsedListing([self.record])
            ),
            patch.object(steps, "ingest_tenders", wraps=ingest_tenders) as ingest,
        ):
            result = steps.ingest_step(self.engine, row, run, self.settings)
        ingest.assert_called_once()
        self.assertEqual(
            result.metrics,
            {
                "discovered": 1,
                "created": 1,
                "changed": 0,
                "unchanged": 0,
                "failed": 0,
                "skipped": 0,
                "limited": 0,
                "scope_count": 1,
            },
        )
        ids = result.children[0].scope_ids
        self.assertNotIn(self.tender_id, ids)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(TenderRevision.tender_id)), ids[0])

    def test_ingestion_limit_preserves_public_counter_meanings(self):
        self.settings.pipeline_max_tenders = 1
        root = self.root("find-a-tender")
        row, run = p.claim_stage(self.engine, root)
        with (
            patch.object(find_tender, "fetch_listing", return_value=""),
            patch.object(
                find_tender,
                "parse_listing",
                return_value=ParsedListing([self.record, self.record], failed=1),
            ),
        ):
            outcome = steps.ingest_step(self.engine, row, run, self.settings)
        self.assertEqual(
            (
                outcome.metrics["discovered"],
                outcome.metrics["created"],
                outcome.metrics["skipped"],
                outcome.metrics["failed"],
            ),
            (3, 1, 1, 1),
        )

    def test_find_tender_documents_explicitly_unsupported(self):
        result = steps.documents_step(
            self.engine,
            SimpleNamespace(scope_ids=[self.tender_id]),
            SimpleNamespace(source_slug="find-a-tender"),
            self.settings,
        )
        self.assertEqual(
            (result.status, result.reason, result.children),
            ("skipped", p.Reason.UNSUPPORTED, []),
        )

    def test_contracts_finder_document_workflow_filters_scope_and_fans_out(self):
        record = DiscoveredDocument(
            tender_external_id=self.record.external_id,
            source_url="https://example.test/a.pdf",
        )
        unrelated = record.model_copy(update={"tender_external_id": "unrelated"})
        row = SimpleNamespace(
            scope_ids=[self.tender_id], config_key=steps.config_key(self.settings)
        )

        def processing(engine, client, records, settings):
            self.assertEqual(self.transactions, 0)
            self.assertEqual(records, [record])
            return DocumentResult(discovered=1)

        with (
            patch.object(contracts_finder, "fetch_releases", return_value={}),
            patch.object(
                steps,
                "discover_documents",
                return_value=DiscoveredDocuments([record, unrelated]),
            ),
            patch.object(steps, "process_documents", side_effect=processing),
        ):
            result = steps.documents_step(
                self.engine,
                row,
                SimpleNamespace(source_slug="contracts-finder"),
                self.settings,
            )
        self.assertEqual(
            [child.stage for child in result.children],
            [p.Stage.ANALYSIS, p.Stage.INDEXING],
        )
        self.assertTrue(
            all(child.entity_id == self.version_id for child in result.children)
        )

    def test_latest_version_selection_does_not_scan_all_historical_versions(self):
        newer = self.add_version(self.document_id, datetime(2026, 9, 2, tzinfo=UTC))
        self.assertEqual(
            steps.latest_versions(self.engine, [self.tender_id], 10), [newer]
        )
        with Session(self.engine) as session, session.begin():
            session.get(DocumentVersion, newer).extraction_status = "empty"
        self.assertEqual(steps.latest_versions(self.engine, [self.tender_id], 10), [])

    def test_analysis_fake_provider_outside_transaction_and_exact_reuse(self):
        row, run = self.child(p.Stage.ANALYSIS)
        with patch.object(
            steps, "OpenAIStructuredClient", return_value=self.structured
        ):
            first = steps.analysis_step(self.engine, row, run, self.settings)
            second = steps.analysis_step(self.engine, row, run, self.settings)
        self.assertEqual(
            (first.status, second.status, second.metrics["reused"]),
            ("completed", "completed", True),
        )
        self.assertEqual(self.structured.calls, 1)
        self.assertTrue(self.structured.closed)
        self.assertEqual(
            [child.stage for child in first.children],
            [p.Stage.MATCHING, p.Stage.CHANGES],
        )

    def test_persisted_provider_failure_reused_and_no_analysis_dependents(self):
        self.structured.error = ProviderError(ProviderFailure.TIMEOUT)
        row, run = self.child(p.Stage.ANALYSIS)
        with patch.object(
            steps, "OpenAIStructuredClient", return_value=self.structured
        ):
            first = steps.analysis_step(self.engine, row, run, self.settings)
            second = steps.analysis_step(self.engine, row, run, self.settings)
        self.assertEqual(
            (first.status, second.status, second.metrics["reused"]),
            ("failed", "failed", True),
        )
        self.assertEqual(first.children, [])
        self.assertEqual(self.structured.calls, 1)
        with patch.object(steps, "OpenAIEmbeddingClient", return_value=self.embedder):
            indexed = steps.indexing_step(self.engine, row, run, self.settings)
        self.assertEqual(indexed.status, "completed")
        self.assertEqual(len(self.embedder.calls), 1)

    def test_ineligible_versions_skip_before_client_creation(self):
        with Session(self.engine) as session, session.begin():
            session.get(DocumentVersion, self.version_id).extracted_text = "  "
        row, run = self.child(p.Stage.ANALYSIS)
        with (
            patch.object(steps, "OpenAIStructuredClient") as ai,
            patch.object(steps, "OpenAIEmbeddingClient") as embedding,
        ):
            self.assertEqual(
                steps.analysis_step(self.engine, row, run, self.settings).status,
                "skipped",
            )
            self.assertEqual(
                steps.indexing_step(self.engine, row, run, self.settings).status,
                "skipped",
            )
        ai.assert_not_called()
        embedding.assert_not_called()

    def test_missing_ai_configuration_fails_only_at_execution(self):
        self.settings.openai_api_key = None
        row, run = self.child(p.Stage.ANALYSIS)
        for step in (steps.analysis_step, steps.indexing_step):
            result = step(self.engine, row, run, self.settings)
            self.assertEqual(
                (result.status, result.reason), ("failed", p.Reason.AI_CONFIG)
            )

    def test_indexing_reuses_embeddings_and_closes_client_on_failure(self):
        row, run = self.child(p.Stage.INDEXING)
        with patch.object(steps, "OpenAIEmbeddingClient", return_value=self.embedder):
            first = steps.indexing_step(self.engine, row, run, self.settings)
            second = steps.indexing_step(self.engine, row, run, self.settings)
        self.assertEqual(first.metrics["embeddings_created"], 1)
        self.assertEqual(second.metrics["embeddings_reused"], 1)
        self.assertEqual(len(self.embedder.calls), 1)
        self.settings.ai_embedding_model = "new-model"
        self.embedder.error = ProviderError(ProviderFailure.API)
        with (
            patch.object(steps, "OpenAIEmbeddingClient", return_value=self.embedder),
            patch.object(self.embedder, "close") as close,
            self.assertRaises(ProviderError),
        ):
            steps.indexing_step(self.engine, row, run, self.settings)
        close.assert_called_once()

    def test_matching_opt_in_bound_and_exact_match_reuse(self):
        analysis_id = self.add_analysis(self.version_id)
        row, run = self.child(p.Stage.MATCHING, "analysis", analysis_id)
        self.assertEqual(
            steps.matching_step(self.engine, row, run, self.settings).reason,
            p.Reason.DISABLED,
        )
        with Session(self.engine) as session, session.begin():
            session.add_all([CompanyProfile(name="One"), CompanyProfile(name="Two")])
        self.settings.auto_match_enabled = True
        self.settings.auto_match_max_companies = 1
        first = steps.matching_step(self.engine, row, run, self.settings)
        second = steps.matching_step(self.engine, row, run, self.settings)
        self.assertEqual(first.metrics, {"matched": 1, "reused": 0, "limited": 1})
        self.assertEqual(second.metrics["reused"], 1)

    def test_matching_and_changes_do_not_run_for_failed_analysis(self):
        analysis_id = self.add_analysis(self.version_id, status="failed")
        row, run = self.child(p.Stage.MATCHING, "analysis", analysis_id)
        self.settings.auto_match_enabled = True
        with (
            patch.object(steps, "match_tender") as match,
            patch.object(steps, "compare_document") as compare,
        ):
            self.assertEqual(
                steps.matching_step(self.engine, row, run, self.settings).status,
                "skipped",
            )
            self.assertEqual(
                steps.changes_step(self.engine, row, run, self.settings).status,
                "skipped",
            )
        match.assert_not_called()
        compare.assert_not_called()

    def test_previous_comparable_analysis_is_closest_and_deterministic(self):
        old = self.add_analysis(self.version_id)
        when = datetime(2026, 9, 2, tzinfo=UTC)
        middle_version = self.add_version(self.document_id, when)
        middle = self.add_analysis(middle_version)
        incompatible_version = self.add_version(
            self.document_id, when + timedelta(days=1)
        )
        self.add_analysis(incompatible_version, model="other-model")
        self.add_analysis(incompatible_version, prompt_version="v2")
        latest_version = self.add_version(self.document_id, when + timedelta(days=2))
        latest = self.add_analysis(latest_version)
        self.assertIsNone(steps.previous_analysis(self.engine, old))
        self.assertEqual(steps.previous_analysis(self.engine, latest), middle)
        row, run = self.child(p.Stage.CHANGES, "analysis", latest)
        first = steps.changes_step(self.engine, row, run, self.settings)
        second = steps.changes_step(self.engine, row, run, self.settings)
        self.assertEqual(
            first.metrics["change_set_id"], second.metrics["change_set_id"]
        )
        self.assertTrue(second.metrics["reused"])

    def test_equal_timestamp_uses_version_id_and_excludes_other_documents(self):
        first = self.add_analysis(self.version_id)
        later = self.add_version(self.document_id, datetime(2026, 9, 1, tzinfo=UTC))
        later_analysis = self.add_analysis(later)
        other = self.add_document(self.tender_id)
        self.add_analysis(self.add_version(other, datetime(2026, 9, 1, tzinfo=UTC)))
        self.assertEqual(steps.previous_analysis(self.engine, later_analysis), first)

    def test_successful_prior_stages_are_not_reenqueued_but_failed_local_work_is(self):
        row, run = self.child(p.Stage.ANALYSIS)
        with patch.object(
            steps, "OpenAIStructuredClient", return_value=self.structured
        ):
            outcome = steps.analysis_step(self.engine, row, run, self.settings)
        p.finish_stage(self.engine, row.id, row.attempt, outcome)
        children = steps.eligible_children(
            self.engine, [self.version_id], row.config_key
        )
        self.assertNotIn(p.Stage.ANALYSIS, [child.stage for child in children])
        self.assertIn(p.Stage.INDEXING, [child.stage for child in children])
        self.assertIn(p.Stage.MATCHING, [child.stage for child in children])
        self.assertIn(p.Stage.CHANGES, [child.stage for child in children])

    def test_changed_worker_configuration_fails_instead_of_mixing_identities(self):
        row, run = self.child(p.Stage.ANALYSIS)
        self.settings.ai_model = "changed"
        result = steps.execute_stage(self.engine, row, run, self.settings)
        self.assertEqual(
            (result.status, result.reason), ("failed", p.Reason.CONFIG_CHANGED)
        )
