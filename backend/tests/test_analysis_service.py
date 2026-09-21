import json
import os
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import JSON, create_engine, event, func, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, ProviderFailure
from app.ai.prompt import TENDER_ANALYSIS_PROMPT
from app.analyze import main
from app.core.config import Settings
from app.models import (
    Base,
    DocumentVersion,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
)
from app.services.analysis import (
    MAX_RAW_RESPONSE_CHARS,
    DocumentVersionNotFound,
    analyze_document,
    prepare_text,
)

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_TEXT = (FIXTURES / "analysis_source.txt").read_text()
RESPONSE = (FIXTURES / "analysis_response.json").read_text()


class FakeClient:
    provider = "test-provider"

    def __init__(self, response=RESPONSE, error=None, before_call=None):
        self.response = response
        self.error = error
        self.before_call = before_call
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.before_call:
            self.before_call()
        if self.error:
            raise self.error
        return self.response


class AnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.transactions = 0

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            self.transactions += 1

        @event.listens_for(self.engine, "commit")
        @event.listens_for(self.engine, "rollback")
        def end(connection):
            self.transactions -= 1

        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session, session.begin():
            source = Source(
                name="Fixture", slug="fixture", base_url="https://example.test"
            )
            tender = Tender(
                source=source, title="Fixture", source_url="https://example.test/tender"
            )
            document = TenderDocument(
                tender=tender, source_url="https://example.test/document"
            )
            version = DocumentVersion(
                document=document,
                content_hash="a" * 64,
                byte_size=1,
                storage_path="aa/fixture.pdf",
                extraction_status="extracted",
                extracted_text=SOURCE_TEXT,
            )
            session.add(version)
            session.flush()
            self.version_id = version.id
            self.document_id = document.id
        self.client = FakeClient(
            before_call=lambda: self.assertEqual(self.transactions, 0)
        )
        blocker = patch(
            "socket.create_connection",
            side_effect=AssertionError("Unit tests cannot access the network"),
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def analyze(self, **overrides):
        options = dict(
            engine=self.engine,
            document_version_id=self.version_id,
            client=self.client,
            model="test-model",
            max_input_chars=60000,
        )
        return analyze_document(**(options | overrides))

    def count(self) -> int:
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(TenderAnalysis))

    def test_first_run_then_exact_repeat_reuses_without_provider_call(self) -> None:
        first = self.analyze()
        second = self.analyze()
        self.assertEqual(first.status, "completed")
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.analysis_id, second.analysis_id)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.client.calls[0]["text"], SOURCE_TEXT.strip())
        with Session(self.engine) as session:
            row = session.get(TenderAnalysis, first.analysis_id)
            self.assertEqual(
                row.input_hash,
                prepare_text(self.client.calls[0]["text"], 60000).input_hash,
            )
            self.assertEqual(json.loads(row.raw_response), json.loads(RESPONSE))
            self.assertEqual(
                row.required_documents, json.loads(RESPONSE)["required_documents"]
            )
            self.assertIsNone(row.failure_reason)

    def test_all_identity_dimensions_append_new_rows_and_preserve_history(self) -> None:
        first = self.analyze()
        revised_prompt = replace(
            TENDER_ANALYSIS_PROMPT,
            version="v2",
            instructions=TENDER_ANALYSIS_PROMPT.instructions
            + "\nRetain source wording.",
        )
        outcomes = [
            self.analyze(prompt=revised_prompt),
            self.analyze(model="other-model"),
            self.analyze(schema_version="v2"),
        ]
        other_provider = FakeClient()
        other_provider.provider = "other-provider"
        outcomes.append(self.analyze(client=other_provider))
        with Session(self.engine) as session, session.begin():
            version = DocumentVersion(
                document_id=self.document_id,
                content_hash="b" * 64,
                byte_size=2,
                storage_path="bb/fixture.pdf",
                extraction_status="extracted",
                extracted_text=SOURCE_TEXT,
            )
            session.add(version)
            session.flush()
            next_id = version.id
        outcomes.append(self.analyze(document_version_id=next_id))
        with Session(self.engine) as session, session.begin():
            session.get(
                DocumentVersion, self.version_id
            ).extracted_text += "\nAdditional source text."
        changed_input = self.analyze()
        outcomes.append(changed_input)
        self.assertEqual(self.count(), 7)
        self.assertTrue(
            all(
                result.status == "completed" and not result.reused
                for result in outcomes
            )
        )
        with Session(self.engine) as session:
            original = session.get(TenderAnalysis, first.analysis_id)
            updated = session.get(TenderAnalysis, changed_input.analysis_id)
            self.assertEqual(original.prompt_version, "v1")
            self.assertEqual(original.model, "test-model")
            self.assertEqual(json.loads(original.raw_response), json.loads(RESPONSE))
            self.assertNotEqual(original.input_hash, updated.input_hash)

    def test_provider_call_has_no_open_database_transaction(self) -> None:
        observations = []
        self.client.before_call = lambda: observations.append(self.transactions)
        self.analyze()
        self.assertEqual(observations, [0])
        self.assertEqual(self.transactions, 0)

    def test_timeout_persists_sanitized_failure_and_repeat_reuses_it(self) -> None:
        self.client.error = ProviderError(ProviderFailure.TIMEOUT)
        first = self.analyze()
        second = self.analyze()
        self.assertEqual(first.status, "failed")
        self.assertTrue(second.reused)
        self.assertEqual(len(self.client.calls), 1)
        with Session(self.engine) as session:
            row = session.get(TenderAnalysis, first.analysis_id)
            self.assertEqual(row.failure_reason, "Provider request timed out")
            self.assertIsNone(row.raw_response)
            self.assertIsNone(row.summary)
            self.assertIsNone(row.required_documents)

    def test_unexpected_provider_error_does_not_leak_secret_details(self) -> None:
        self.client.error = RuntimeError("Authorization: Bearer sensitive-test-key")
        with self.assertLogs("app.services.analysis", level="WARNING") as logs:
            result = self.analyze()
        with Session(self.engine) as session:
            row = session.get(TenderAnalysis, result.analysis_id)
            self.assertEqual(row.failure_reason, "Provider call failed unexpectedly")
            self.assertIsNone(row.raw_response)
        self.assertNotIn("sensitive-test-key", " ".join(logs.output))

    def test_malformed_output_is_retained_separately_from_validated_columns(
        self,
    ) -> None:
        for response in ('{"unexpected":true}', "```json\n{}\n```", '{"summary":'):
            with self.subTest(response=response):
                client = FakeClient(response=response)
                result = self.analyze(client=client, model=f"malformed-{len(response)}")
                with Session(self.engine) as session:
                    row = session.get(TenderAnalysis, result.analysis_id)
                    self.assertEqual(row.status, "failed")
                    self.assertEqual(row.raw_response, response)
                    self.assertEqual(
                        row.failure_reason, "Provider output failed schema validation"
                    )
                    self.assertIsNone(row.eligibility_requirements)
                    self.assertIsNone(row.summary_evidence)

    def test_unsupported_evidence_fails_without_accepting_any_claims(self) -> None:
        payload = json.loads(RESPONSE)
        payload["required_documents"][0]["evidence"] = "A fabricated quotation"
        result = self.analyze(client=FakeClient(json.dumps(payload)))
        with Session(self.engine) as session:
            row = session.get(TenderAnalysis, result.analysis_id)
            self.assertEqual(row.status, "failed")
            self.assertIn("Evidence not found", row.failure_reason)
            self.assertIsNone(row.required_documents)
            self.assertIsNotNone(row.raw_response)

    def test_oversized_and_non_text_provider_responses_fail_safely(self) -> None:
        for response, model in (
            ("x" * (MAX_RAW_RESPONSE_CHARS + 1), "large"),
            ({}, "not-text"),
        ):
            result = self.analyze(client=FakeClient(response), model=model)
            with Session(self.engine) as session:
                row = session.get(TenderAnalysis, result.analysis_id)
                self.assertEqual(row.status, "failed")
                self.assertLessEqual(
                    len(row.raw_response or ""), MAX_RAW_RESPONSE_CHARS
                )

    def test_ineligible_versions_skip_without_call_or_analysis_row(self) -> None:
        for status, text in (
            ("extracted", None),
            ("extracted", ""),
            ("extracted", " \x00\n "),
            ("empty", SOURCE_TEXT),
            ("failed", SOURCE_TEXT),
        ):
            with (
                self.subTest(status=status, text=text),
                Session(self.engine) as session,
                session.begin(),
            ):
                version = session.get(DocumentVersion, self.version_id)
                version.extraction_status = status
                version.extracted_text = text
            self.assertEqual(self.analyze().status, "skipped")
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.count(), 0)

    def test_missing_version_fails_without_call_or_orphan(self) -> None:
        with self.assertRaises(DocumentVersionNotFound):
            self.analyze(document_version_id=999)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.count(), 0)

    def test_invalid_storage_characters_cannot_enter_validated_json(self) -> None:
        for invalid in ("\x00", "\ud800"):
            payload = json.loads(RESPONSE)
            payload["required_documents"][0]["value"] += invalid
            response = json.dumps(payload)
            result = self.analyze(
                client=FakeClient(response), model=f"invalid-{ord(invalid)}"
            )
            with Session(self.engine) as session:
                row = session.get(TenderAnalysis, result.analysis_id)
                self.assertEqual(row.status, "failed")
                self.assertIsNone(row.required_documents)
                self.assertEqual(row.raw_response, response)

    def test_malformed_raw_output_is_escaped_for_postgresql_text_storage(self) -> None:
        result = self.analyze(client=FakeClient("not JSON\x00\ud800"))
        with Session(self.engine) as session:
            row = session.get(TenderAnalysis, result.analysis_id)
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.raw_response, "not JSON\\u0000\\ud800")

    def test_interleaved_duplicate_call_reuses_winner_without_overwrite(self) -> None:
        winner = []
        inner_client = FakeClient()
        self.client.before_call = lambda: winner.append(
            self.analyze(client=inner_client)
        )
        self.client.response = '{"invalid":"losing response"}'
        outer = self.analyze()
        self.assertTrue(outer.reused)
        self.assertEqual(outer.status, "completed")
        self.assertEqual(outer.analysis_id, winner[0].analysis_id)
        self.assertEqual(self.count(), 1)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(len(inner_client.calls), 1)
        with Session(self.engine) as session:
            self.assertEqual(
                json.loads(session.get(TenderAnalysis, outer.analysis_id).raw_response),
                json.loads(RESPONSE),
            )

    def test_database_identity_and_status_constraints(self) -> None:
        result = self.analyze()
        with Session(self.engine) as session:
            original = session.get(TenderAnalysis, result.analysis_id)
            values = {
                column.name: getattr(original, column.name)
                for column in TenderAnalysis.__table__.c
                if column.name != "id"
            }
        with (
            Session(self.engine) as session,
            self.assertRaises(IntegrityError),
            session.begin(),
        ):
            session.add(TenderAnalysis(**values))
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(
                TenderAnalysis.__table__.update().values(status="unknown")
            )

    def test_version_deletion_is_restricted_when_analysis_exists(self) -> None:
        self.analyze()
        with Session(self.engine) as session:
            version = session.get(DocumentVersion, self.version_id)
            self.assertEqual(len(version.analyses), 1)
            session.delete(version)
            with self.assertRaises(IntegrityError):
                session.commit()
        self.assertEqual(self.count(), 1)

    def test_prepare_only_cli_on_sqlite_fixture_needs_no_ai_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(
                _env_file=None, postgres_password="test-only", ai_max_input_chars=200
            )
        with (
            patch("app.analyze.logging.basicConfig"),
            patch("app.analyze.Settings", return_value=settings),
            patch("app.analyze.create_database_engine", return_value=self.engine),
            patch.object(self.engine, "dispose") as dispose,
            patch(
                "app.analyze.OpenAIStructuredClient",
                side_effect=AssertionError("Preview created a provider"),
            ),
            redirect_stdout(StringIO()) as output,
        ):
            code = main(
                ["--document-version-id", str(self.version_id), "--prepare-only"]
            )
        self.assertEqual(code, 0)
        dispose.assert_called_once()
        self.assertIn("input_chars=200", output.getvalue())
        self.assertIn("truncated=true persisted=false", output.getvalue())
        self.assertIn(prepare_text(SOURCE_TEXT, 200).input_hash, output.getvalue())
        self.assertNotIn("ISO 9001", output.getvalue())
        self.assertEqual(self.count(), 0)


class AnalysisModelTests(unittest.TestCase):
    def test_json_variants_fk_and_append_only_relationship(self) -> None:
        table = TenderAnalysis.__table__
        for column in table.c:
            if isinstance(column.type, JSON):
                self.assertEqual(
                    str(column.type.compile(dialect=postgresql.dialect())), "JSONB"
                )
                self.assertEqual(
                    str(column.type.compile(dialect=sqlite.dialect())), "JSON"
                )
                self.assertTrue(column.type.none_as_null)
        foreign_key = next(iter(table.foreign_keys))
        self.assertEqual(foreign_key.target_fullname, "document_versions.id")
        self.assertEqual(foreign_key.ondelete, "RESTRICT")
        self.assertEqual(table.c.input_hash.type.length, 64)
        self.assertNotIn("updated_at", table.c)
        relation = inspect(DocumentVersion).relationships.analyses
        self.assertEqual(relation.passive_deletes, "all")
        self.assertNotIn("delete", relation.cascade)
        self.assertEqual(
            inspect(TenderAnalysis).relationships.document_version.back_populates,
            "analyses",
        )
