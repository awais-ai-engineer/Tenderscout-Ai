import json
import socket
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from change_fixtures import output
from fastapi.testclient import TestClient
from rag_fixtures import CHUNKING, EMBEDDING, RagDatabaseMixin
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.product_support import MAX_PRODUCT_REQUEST_BODY_BYTES
from app.core.config import Settings
from app.main import app
from app.models import (
    Alert,
    DocumentVersion,
    Tender,
    TenderAnalysis,
    TenderDocument,
    TenderRevision,
)
from app.services import pipeline, product_actions, queries
from app.services.change_detection import compare_document
from app.services.indexing import index_document
from app.services.notifications import create_match_alert, create_update_alerts
from app.services.revisions import capture_revision, ensure_baseline

ORIGINAL_CONNECT = socket.socket.connect


class ProductApiTests(RagDatabaseMixin, unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with patch("rag_fixtures.create_engine", return_value=engine):
            super().setUp()
        self.settings = Settings(
            _env_file=None,
            postgres_password="test-only",
            openai_api_key="test-only",
            ai_model="synthetic-answer",
            ai_embedding_model=EMBEDDING.model,
        )
        self.embedder.provider = self.answerer.provider = "openai"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] in (
                "127.0.0.1",
                "::1",
                "localhost",
            ):
                return ORIGINAL_CONNECT(sock, address)
            raise AssertionError("External network forbidden")

        self.stack.enter_context(patch("socket.socket.connect", new=local_only))
        self.stack.enter_context(
            patch("app.main.create_database_engine", return_value=self.engine)
        )
        self.stack.enter_context(patch("app.main.Settings", return_value=self.settings))
        self.stack.enter_context(
            patch.object(
                product_actions, "OpenAIEmbeddingClient", return_value=self.embedder
            )
        )
        self.stack.enter_context(
            patch.object(
                product_actions, "OpenAIStructuredClient", return_value=self.answerer
            )
        )
        self.client = self.stack.enter_context(
            TestClient(app, raise_server_exceptions=False)
        )
        with Session(engine) as session, session.begin():
            version = session.get(DocumentVersion, self.version_id)
            document = session.get(TenderDocument, version.document_id)
            self.document_id, self.tender_id = document.id, document.tender_id
            tender = session.get(Tender, self.tender_id)
            tender.title, tender.organization, tender.category = (
                "Cloud services",
                "Authority North",
                "IT",
            )
            tender.deadline = datetime.now(UTC) + timedelta(days=10)
            baseline = ensure_baseline(session, tender)
            tender.title = "Managed cloud services"
            capture_revision(session, tender, baseline, datetime.now(UTC))
            analysis = TenderAnalysis(
                document_version_id=self.version_id,
                analysis_schema_version="v1",
                provider="synthetic",
                model="test-model",
                prompt_version="v1",
                input_hash="a" * 64,
                status="completed",
                raw_response="private provider body",
                **output().model_dump(),
            )
            session.add(analysis)
            session.flush()
            self.analysis_id = analysis.id

    def get(self, path, status=200):
        response = self.client.get("/api/v1" + path)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def company(self):
        response = self.client.post(
            "/api/v1/companies",
            json={
                "name": "Example company",
                "annual_revenue": "120000.50",
                "currency": "GBP",
                "capabilities": [{"name": "Cloud services"}],
                "certifications": [{"name": "ISO 27001", "valid_until": "2028-01-01"}],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def index(self):
        index_document(
            self.engine,
            self.version_id,
            self.embedder,
            embedding=EMBEDDING,
            chunking=CHUNKING,
        )

    def ask(self, question="What is the deadline?"):
        return self.client.post(
            f"/api/v1/document-versions/{self.version_id}/ask",
            json={"question": question},
        )

    def test_tender_cursor_filters_and_utc_fields(self):
        first = self.get("/tenders?limit=1")
        second = self.get(f"/tenders?limit=1&cursor={first['next_cursor']}")
        self.assertGreater(first["items"][0]["id"], second["items"][0]["id"])
        self.assertIsNone(second["next_cursor"])
        for suffix in (
            "search=CLOUD",
            "organization=north",
            "category=IT",
            "deadline_after=2026-01-01T00%3A00%3A00Z",
        ):
            items = self.get("/tenders?" + suffix)["items"]
            self.assertIn(self.tender_id, [item["id"] for item in items])
        self.assertEqual(self.get("/tenders?source=contracts-finder")["items"], [])
        self.assertEqual(self.get("/tenders?search=%25")["items"], [])
        self.assertTrue(second["items"][0]["last_seen_at"].endswith("Z"))

    def test_detail_has_summaries_and_no_sensitive_fields(self):
        result = self.get(f"/tenders/{self.tender_id}")
        self.assertEqual(result["latest_revision_index"], 2)
        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["analyses"]["items"][0]["id"], self.analysis_id)
        self.assertEqual(result["latest_metadata_change"]["change_count"], 1)
        text = json.dumps(result)
        for secret in (
            "storage_path",
            "extracted_text",
            "raw_response",
            "private provider body",
            '"embedding"',
        ):
            self.assertNotIn(secret, text)

    def test_documents_index_readiness_requires_complete_current_model(self):
        path = f"/tenders/{self.tender_id}/documents"
        version = self.get(path)["items"][0]["versions"]["items"][0]
        self.assertTrue(version["has_analysis"])
        self.assertFalse(version["is_indexed"])
        self.index()
        self.assertTrue(
            self.get(path)["items"][0]["versions"]["items"][0]["is_indexed"]
        )
        for field, value in (
            ("ai_embedding_model", "unavailable-model"),
            ("rag_chunk_size_chars", self.settings.rag_chunk_size_chars + 1),
            ("rag_chunk_overlap_chars", self.settings.rag_chunk_overlap_chars + 1),
        ):
            with self.subTest(field=field), patch.object(self.settings, field, value):
                self.assertFalse(
                    self.get(path)["items"][0]["versions"]["items"][0]["is_indexed"]
                )
        self.assertNotIn(
            "storage_path",
            json.dumps(self.get(f"/documents/{self.document_id}/versions")),
        )

    def test_analysis_is_structured_and_latest_policy_is_404(self):
        detail = self.get(f"/analyses/{self.analysis_id}")
        self.assertEqual(detail["facts"], output().model_dump())
        self.assertNotIn("raw_response", detail)
        self.assertEqual(
            self.get(f"/document-versions/{self.version_id}/analysis")["id"],
            self.analysis_id,
        )
        self.get(f"/document-versions/{self.other_version_id}/analysis", 404)

    def test_missing_and_validation_errors_share_contract(self):
        for path in (
            "/tenders/99999",
            "/analyses/99999",
            "/companies/99999",
            "/matches/99999",
            "/pipeline/runs/99999",
            "/unknown",
        ):
            self.assertEqual(set(self.get(path, 404)), {"error"})
        for path in (
            "/tenders?limit=101",
            "/tenders?cursor=0",
            "/tenders?source=bad",
            "/tenders?deadline_after=bad",
            "/tenders/0",
            "/companies?limit=0",
        ):
            self.assertEqual(self.get(path, 422)["error"]["code"], "invalid_request")

    def test_company_creation_reuses_strict_json_decimal_and_date_rules(self):
        company_id = self.company()
        detail = self.get(f"/companies/{company_id}")
        self.assertEqual(detail["profile"]["annual_revenue"], "120000.50")
        self.assertEqual(
            detail["profile"]["certifications"][0]["valid_until"], "2028-01-01"
        )
        self.assertEqual(self.get("/companies")["items"][0]["capability_count"], 1)
        for body in (
            {"name": ""},
            {"name": "Company", "employee_count": "10"},
            {"name": "Company", "secret": "sensitive-input"},
        ):
            response = self.client.post("/api/v1/companies", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("sensitive-input", response.text)

    def test_matching_actions_and_gets_do_not_recompute(self):
        company_id = self.company()
        response = self.client.post(
            "/api/v1/matches",
            json={"company_id": company_id, "analysis_id": self.analysis_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        match = response.json()
        with patch(
            "app.services.matching.match_tender",
            side_effect=AssertionError("GET must not recompute"),
        ):
            self.assertEqual(
                self.get(f"/matches/{match['match_id']}")["match_id"], match["match_id"]
            )
            self.assertEqual(
                len(self.get(f"/companies/{company_id}/matches")["items"]), 1
            )
            self.assertEqual(
                len(self.get(f"/tenders/{self.tender_id}/matches")["items"]), 1
            )
        self.assertIn("coverage_ratio", match)
        self.assertNotIn("company_snapshot", match)

    def test_ask_supported_answer_preserves_citations_and_reuses(self):
        self.index()
        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["citations"][0]["document_version_id"], self.version_id)
        self.assertIn("quote", result["citations"][0])
        self.assertNotIn("page_number", result["citations"][0])
        self.assertTrue(self.ask().json()["reused"])

    def test_ask_insufficient_is_success(self):
        self.index()
        self.answerer.response = json.dumps(
            {"answer": None, "citations": [], "insufficient_evidence": True}
        )
        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "insufficient")

    def test_ask_distinguishes_index_configuration_provider_and_validation(self):
        self.assertEqual(self.ask().json()["error"]["code"], "document_not_indexed")
        self.settings.openai_api_key = None
        self.assertEqual(self.ask().json()["error"]["code"], "ai_configuration_missing")
        from pydantic import SecretStr

        self.settings.openai_api_key = SecretStr("test-only")
        self.index()
        self.answerer.error = RuntimeError("secret-provider-body")
        result = self.ask("First question")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()["error"]["code"], "provider_unavailable")
        self.assertNotIn("secret-provider-body", result.text)
        self.answerer.error = None
        self.answerer.response = json.dumps(
            {
                "answer": "Invented",
                "citations": [{"chunk_id": 999, "quote": "invented"}],
                "insufficient_evidence": False,
            }
        )
        result = self.ask("Different question")
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json()["error"]["code"], "answer_validation_failed")

    def test_revision_and_stored_metadata_changes(self):
        revisions = self.get(f"/tenders/{self.tender_id}/revisions?limit=1")
        self.assertEqual(revisions["items"][0]["revision_index"], 2)
        self.assertNotIn("description", revisions["items"][0])
        changes = self.get(f"/tenders/{self.tender_id}/changes")["items"]
        detail = self.get(f"/changes/metadata/{changes[0]['id']}")
        self.assertEqual(detail["changes"][0]["old"], "Cloud services")
        self.assertEqual(detail["changes"][0]["new"], "Managed cloud services")

    def test_document_change_detail_and_scoped_listing(self):
        with Session(self.engine) as session, session.begin():
            version = DocumentVersion(
                document_id=self.document_id,
                content_hash="b" * 64,
                byte_size=1,
                storage_path="private-path",
                extraction_status="extracted",
                downloaded_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(version)
            session.flush()
            analysis = TenderAnalysis(
                document_version_id=version.id,
                analysis_schema_version="v1",
                provider="synthetic",
                model="test-model",
                prompt_version="v1",
                input_hash="b" * 64,
                status="completed",
                **output(
                    required_documents=[
                        {"value": "Certificate", "evidence": "Exact evidence"}
                    ]
                ).model_dump(),
            )
            session.add(analysis)
            session.flush()
            analysis_id = analysis.id
        result = compare_document(self.engine, self.analysis_id, analysis_id)
        detail = self.get(f"/changes/document/{result.change_set_id}")
        self.assertEqual(detail["from_analysis_id"], self.analysis_id)
        self.assertEqual(detail["to_analysis_id"], analysis_id)
        self.assertIsNone(detail["from_revision_id"])
        self.assertEqual(detail["changes"][0]["new"]["evidence"], "Exact evidence")
        self.assertEqual(
            len(self.get(f"/tenders/{self.tender_id}/changes?kind=document")["items"]),
            1,
        )

    def test_pipeline_trigger_status_and_no_maintenance_endpoint(self):
        run_id, _ = pipeline.create_run(self.engine, "contracts-finder")
        with patch(
            "app.worker.tasks.trigger_pipeline",
            return_value={
                "run_id": run_id,
                "source": "contracts-finder",
                "status": "queued",
                "celery_task_id": "test-task",
                "reused": True,
            },
        ) as trigger:
            response = self.client.post(
                "/api/v1/pipeline/runs", json={"source": "contracts-finder"}
            )
        self.assertEqual(response.status_code, 202, response.text)
        trigger.assert_called_once()
        self.assertEqual(
            self.get(f"/pipeline/runs/{run_id}")["stages"][0]["status"], "queued"
        )
        self.assertEqual(len(self.get("/pipeline/runs")["items"]), 1)
        self.assertEqual(
            self.client.post("/api/v1/pipeline/mark-stale").status_code, 404
        )
        self.settings.celery_task_always_eager = True
        self.assertEqual(
            self.client.post(
                "/api/v1/pipeline/runs", json={"source": "contracts-finder"}
            ).status_code,
            503,
        )

    def test_dashboard_counts_and_bounded_lists(self):
        result = self.get("/dashboard/summary")
        self.assertEqual(result["tender_count"], 2)
        self.assertEqual(result["active_tenders_count"], 1)
        self.assertEqual(len(result["recent_changes"]), 1)

    def test_saved_tenders_are_company_scoped_and_idempotent(self):
        company_id = self.company()
        path = f"/api/v1/saved/{self.tender_id}?company_id={company_id}"
        first = self.client.post(path, json={})
        second = self.client.post(path, json={})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        saved = self.get(f"/saved?company_id={company_id}")["items"]
        self.assertEqual([item["tender"]["id"] for item in saved], [self.tender_id])
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.get(f"/saved?company_id={company_id}")["items"], [])
        self.assertEqual(
            self.client.post(
                f"/api/v1/saved/99999?company_id={company_id}", json={}
            ).status_code,
            404,
        )

    def test_preferences_validate_and_alerts_can_be_read(self):
        company_id = self.company()
        path = f"/api/v1/notification-preferences?company_id={company_id}"
        invalid = self.client.put(
            path,
            json={"email_enabled": True, "notification_email": "invalid"},
        )
        self.assertEqual(invalid.status_code, 422)
        body = {
            "email_enabled": True,
            "notification_email": "alerts@example.com",
            "minimum_match_score": 75,
            "new_match_alerts": True,
            "tender_change_alerts": True,
            "deadline_reminders": True,
            "delivery_mode": "daily_digest",
        }
        self.assertEqual(self.client.put(path, json=body).status_code, 200)
        with Session(self.engine) as session, session.begin():
            alert = Alert(
                company_id=company_id,
                tender_id=self.tender_id,
                type="tender_updated",
                title="Tender updated",
                message="A material change was recorded.",
                dedupe_key="test-update",
                delivery_status="pending",
            )
            session.add(alert)
            session.flush()
            alert_id = alert.id
        self.assertEqual(
            len(self.get(f"/alerts?company_id={company_id}&unread_only=true")["items"]),
            1,
        )
        response = self.client.patch(
            f"/api/v1/alerts/{alert_id}/read?company_id={company_id}", json={}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["read_at"])
        self.assertEqual(
            self.get(f"/alerts?company_id={company_id}&unread_only=true")["items"],
            [],
        )

    def test_match_threshold_and_update_alert_deduplication(self):
        company_id = self.company()
        match = self.client.post(
            "/api/v1/matches",
            json={"company_id": company_id, "analysis_id": self.analysis_id},
        ).json()
        path = f"/api/v1/notification-preferences?company_id={company_id}"
        self.assertEqual(
            self.client.put(path, json={"minimum_match_score": 100}).status_code,
            200,
        )
        score = match["score"]
        if score is not None and score < 100:
            self.assertEqual(
                create_match_alert(self.engine, match["match_id"]), (None, False)
            )
        self.client.put(path, json={"minimum_match_score": 0})
        first_id, created = create_match_alert(self.engine, match["match_id"])
        if match["eligibility_status"] != "ineligible" and score is not None:
            self.assertTrue(created)
            self.assertEqual(
                create_match_alert(self.engine, match["match_id"]), (first_id, False)
            )
        with Session(self.engine) as session:
            revision_id = session.scalar(
                select(TenderRevision.id)
                .where(TenderRevision.tender_id == self.tender_id)
                .order_by(TenderRevision.id.desc())
            )
        update_ids = create_update_alerts(self.engine, self.tender_id, revision_id)
        self.assertEqual(len(update_ids), 1)
        self.assertEqual(
            create_update_alerts(self.engine, self.tender_id, revision_id), []
        )

    def test_database_errors_are_sanitized_and_request_bodies_bounded(self):
        with patch.object(
            queries,
            "tenders",
            side_effect=OperationalError(
                "private SQL", {}, Exception("secret password")
            ),
        ):
            response = self.client.get("/api/v1/tenders")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)
        self.assertNotIn("secret", response.text)
        response = self.client.post(
            "/api/v1/companies", content=b"x" * (MAX_PRODUCT_REQUEST_BODY_BYTES + 1)
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")

    def test_body_above_old_limit_reaches_company_validation(self):
        response = self.client.post(
            "/api/v1/companies", json={"name": "x" * (256 * 1024 + 1)}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_cors_only_allows_configured_origin(self):
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        }
        response = self.client.options("/api/v1/companies", headers=headers)
        self.assertEqual(
            response.headers["access-control-allow-origin"], "http://localhost:3000"
        )
        response = self.client.options(
            "/api/v1/companies", headers=headers | {"Origin": "https://untrusted.test"}
        )
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(response.json()["error"]["code"], "cors_rejected")

    def test_list_query_count_is_constant_and_does_not_select_document_text(self):
        sql = []

        def capture(connection, cursor, statement, parameters, context, many):
            sql.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            self.get("/tenders")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(sql), 1)
        self.assertNotIn("extracted_text", sql[0])
        self.assertNotIn("raw_response", sql[0])

    def test_openapi_health_and_unexpected_error_contract(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        schema = self.client.get("/openapi.json").json()
        for path, operations in schema["paths"].items():
            if path.startswith("/api/v1/"):
                for operation in operations.values():
                    self.assertEqual(
                        operation["responses"]["422"]["content"]["application/json"][
                            "schema"
                        ]["$ref"],
                        "#/components/schemas/ErrorEnvelope",
                    )
        with patch.object(
            queries, "tenders", side_effect=RuntimeError("private-token")
        ):
            response = self.client.get("/api/v1/tenders")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertNotIn("private-token", response.text)

    def test_origins_validate_and_secrets_remain_redacted(self):
        from pydantic import ValidationError

        for origin in (
            "*",
            "https://*.test",
            "https://user:pass@example.test",
            "https://example.test/path",
            "https://example.test?secret=value",
            "ftp://example.test",
            "https://example.test:99999",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                Settings(
                    _env_file=None,
                    postgres_password="private-password",
                    cors_allowed_origins=[origin],
                )
        settings = Settings(_env_file=None, postgres_password="private-password")
        self.assertNotIn("private-password", repr(settings))
        self.assertNotIn("private-password", settings.model_dump_json())
