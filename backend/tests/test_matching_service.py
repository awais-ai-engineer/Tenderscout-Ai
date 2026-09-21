import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import JSON, create_engine, delete, event, func, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.company import main as company_main
from app.match import main as match_main
from app.models import (
    Base,
    CompanyCapability,
    CompanyCertification,
    CompanyExperience,
    CompanyProfile,
    DocumentVersion,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
    TenderMatch,
)
from app.schemas.company import CompanyInput
from app.services.companies import create_company, show_company
from app.services.matching import compute_match, match_tender

FIXTURES = Path(__file__).parent / "fixtures"


class MatchingServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.transactions = 0

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            self.transactions += 1

        @event.listens_for(self.engine, "commit")
        @event.listens_for(self.engine, "rollback")
        def end(connection):
            self.transactions -= 1

        Base.metadata.create_all(self.engine)
        self.profile = CompanyInput.model_validate_json(
            (FIXTURES / "company_profile.json").read_bytes()
        )
        self.company_id = create_company(self.engine, self.profile)
        self.analysis_data = json.loads(
            (FIXTURES / "analysis_response.json").read_text()
        )
        with Session(self.engine) as session, session.begin():
            source = Source(
                name="Synthetic", slug="synthetic", base_url="https://example.test"
            )
            tender = Tender(
                source=source,
                title="Synthetic",
                location="UK",
                source_url="https://example.test/tender",
            )
            document = TenderDocument(
                tender=tender, source_url="https://example.test/document"
            )
            version = DocumentVersion(
                document=document,
                content_hash="a" * 64,
                byte_size=1,
                storage_path="synthetic.pdf",
                extraction_status="extracted",
                extracted_text="Synthetic",
            )
            session.add(version)
            session.flush()
            self.version_id = version.id
        self.analysis_id = self.add_analysis()
        for target in (
            "socket.socket.connect",
            "socket.create_connection",
            "httpx.Client.send",
        ):
            blocker = patch(target, side_effect=AssertionError("No network permitted"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def add_analysis(self, **changes):
        values = dict(
            document_version_id=self.version_id,
            analysis_schema_version="v1",
            provider="synthetic",
            model="synthetic",
            prompt_version="v1",
            input_hash="a" * 64,
            status="completed",
            **self.analysis_data,
        )
        values.update(changes)
        with Session(self.engine) as session, session.begin():
            row = TenderAnalysis(**values)
            session.add(row)
            session.flush()
            return row.id

    def match(self, **changes):
        return match_tender(
            self.engine,
            **(
                {"company_id": self.company_id, "analysis_id": self.analysis_id}
                | changes
            ),
        )

    def row_snapshot(self, model, row_id):
        with Session(self.engine) as session:
            row = session.get(model, row_id)
            return {
                column.name: getattr(row, column.name) for column in model.__table__.c
            }

    def test_import_round_trip_preserves_children_and_unknowns(self):
        self.assertEqual(show_company(self.engine, self.company_id), self.profile)
        with Session(self.engine) as session:
            row = session.get(CompanyProfile, self.company_id)
            self.assertIsNotNone(row.created_at)
            self.assertIsNotNone(row.updated_at)
            self.assertEqual(row.capabilities[0].name_key, "azure cloud migration")
            self.assertIsNotNone(row.certifications[0].created_at)
            self.assertIsNone(row.certifications[0].valid_from)

    def test_import_transaction_rolls_back_all_children(self):
        @event.listens_for(self.engine, "before_cursor_execute")
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO company_certifications"):
                raise RuntimeError("Synthetic failure")

        try:
            with self.assertRaises(RuntimeError):
                create_company(self.engine, self.profile)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(CompanyProfile)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(CompanyCapability)), 1
            )

    def test_compute_outside_transaction_and_reuse_without_recompute(self):
        def compare(*args):
            self.assertEqual(self.transactions, 0)
            return compute_match(*args)

        with patch(
            "app.services.matching.compute_match", side_effect=compare
        ) as compute:
            first = self.match()
            second = self.match()
            self.assertEqual(compute.call_count, 1)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.match_id, second.match_id)
        self.assertEqual(first.score, second.score)

    def test_version_and_parent_identity_append_preserves_history(self):
        analysis_before = self.row_snapshot(TenderAnalysis, self.analysis_id)
        first = self.match()
        before = self.row_snapshot(TenderMatch, first.match_id)
        with patch("app.services.matching.MATCHER_VERSION", "v2"):
            second = self.match()
        another_company = create_company(self.engine, self.profile)
        third = self.match(company_id=another_company)
        another_analysis = self.add_analysis(input_hash="b" * 64)
        fourth = self.match(analysis_id=another_analysis)
        self.assertEqual(
            len({row.match_id for row in (first, second, third, fourth)}), 4
        )
        self.assertEqual(self.row_snapshot(TenderMatch, first.match_id), before)
        self.assertEqual(
            self.row_snapshot(TenderAnalysis, self.analysis_id), analysis_before
        )

    def test_snapshot_survives_company_edit_and_exact_identity_reuses(self):
        first = self.match()
        before = self.row_snapshot(TenderMatch, first.match_id)
        with Session(self.engine) as session, session.begin():
            session.get(CompanyProfile, self.company_id).name = "Edited assertion"
        self.assertTrue(self.match().reused)
        self.assertEqual(self.row_snapshot(TenderMatch, first.match_id), before)
        self.assertEqual(before["company_snapshot"]["name"], self.profile.name)

    def test_rechecks_identity_after_compute(self):
        def intervening_writer(*args):
            values = compute_match(*args)
            with Session(self.engine) as session, session.begin():
                session.add(
                    TenderMatch(
                        company_id=self.company_id,
                        tender_analysis_id=self.analysis_id,
                        matcher_version="v1",
                        **values,
                    )
                )
            return values

        with patch(
            "app.services.matching.compute_match", side_effect=intervening_writer
        ):
            self.assertTrue(self.match().reused)

    def test_invalid_parents_and_failed_analysis_not_persisted(self):
        failed = self.add_analysis(input_hash="f" * 64, status="failed")
        unsupported = self.add_analysis(
            input_hash="e" * 64, analysis_schema_version="v99"
        )
        for changes in (
            {"company_id": 999},
            {"analysis_id": 999},
            {"analysis_id": failed},
            {"analysis_id": unsupported},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.match(**changes)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(TenderMatch)), 0
            )

    def test_company_children_cascade_with_loaded_and_unloaded_relationships(self):
        for orm in (True, False):
            company_id = create_company(self.engine, self.profile)
            with Session(self.engine) as session, session.begin():
                if orm:
                    company = session.get(CompanyProfile, company_id)
                    self.assertTrue(company.capabilities)
                    self.assertTrue(company.certifications)
                    self.assertTrue(company.experience)
                    session.delete(company)
                else:
                    session.execute(
                        delete(CompanyProfile).where(CompanyProfile.id == company_id)
                    )
            with Session(self.engine) as session:
                for child in (
                    CompanyCapability,
                    CompanyCertification,
                    CompanyExperience,
                ):
                    self.assertIsNone(
                        session.scalar(
                            select(child).where(child.company_id == company_id)
                        )
                    )

    def test_match_restricts_company_and_analysis_delete(self):
        matched = self.match()
        for model, row_id in (
            (CompanyProfile, self.company_id),
            (TenderAnalysis, self.analysis_id),
        ):
            for orm in (True, False):
                with (
                    self.subTest(model=model, orm=orm),
                    self.assertRaises(IntegrityError),
                    Session(self.engine) as session,
                    session.begin(),
                ):
                    if orm:
                        row = session.get(model, row_id)
                        if model is CompanyProfile:
                            self.assertTrue(row.matches)
                            self.assertTrue(row.capabilities)
                        session.delete(row)
                    else:
                        session.execute(delete(model).where(model.id == row_id))
        self.assertTrue(self.row_snapshot(TenderMatch, matched.match_id))
        self.assertEqual(show_company(self.engine, self.company_id), self.profile)

    def test_foreign_keys_uniqueness_and_checks_are_enforced(self):
        first = self.match()
        data = self.row_snapshot(TenderMatch, first.match_id)
        data.pop("id")
        for change in (
            {},
            {"company_id": 999},
            {"tender_analysis_id": 999},
            {"matcher_version": "v2", "score": 101},
            {"matcher_version": "v2", "coverage_ratio": -1},
            {"matcher_version": "v2", "eligibility_status": "winner"},
        ):
            with (
                self.subTest(change=change),
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(TenderMatch(**(data | change)))
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.add(
                CompanyCapability(
                    company_id=self.company_id,
                    name="AZURE CLOUD MIGRATION",
                    name_key="azure cloud migration",
                )
            )
        for model, values in (
            (CompanyCapability, {"name": "Test", "name_key": "test"}),
            (CompanyCertification, {"name": "Test"}),
            (CompanyExperience, {"title": "Test"}),
        ):
            with (
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(model(company_id=999, **values))

    def test_json_dialects_relationships_and_match_timestamps(self):
        row = self.row_snapshot(TenderMatch, self.match().match_id)
        self.assertIsInstance(row["company_snapshot"], dict)
        self.assertIsInstance(row["unknown_requirements"], list)
        self.assertIsNotNone(row["created_at"])
        self.assertNotIn("updated_at", TenderMatch.__table__.c)
        for column in TenderMatch.__table__.c:
            if isinstance(column.type, JSON):
                self.assertIsInstance(
                    column.type.dialect_impl(postgresql.dialect()), postgresql.JSONB
                )
                self.assertIsInstance(column.type.dialect_impl(sqlite.dialect()), JSON)
        self.assertEqual(
            inspect(CompanyProfile).relationships["matches"].passive_deletes, "all"
        )
        for key in ("capabilities", "certifications", "experience"):
            self.assertIn(
                "delete-orphan", inspect(CompanyProfile).relationships[key].cascade
            )

    def test_company_and_match_cli_with_sqlite_without_api_key(self):
        # Preserve this in-memory fixture when each CLI disposes its engine.
        with (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only"}, clear=True),
            patch.object(self.engine, "dispose"),
            patch("app.company.create_database_engine", return_value=self.engine),
            patch("app.match.create_database_engine", return_value=self.engine),
        ):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    company_main(
                        ["create", "--file", str(FIXTURES / "company_profile.json")]
                    ),
                    0,
                )
            company_id = int(output.getvalue().strip().split("=")[1])
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    company_main(["show", "--company-id", str(company_id)]), 0
                )
            self.assertEqual(json.loads(output.getvalue())["name"], self.profile.name)
            for reused in ("false", "true"):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        match_main(
                            [
                                "--company-id",
                                str(company_id),
                                "--analysis-id",
                                str(self.analysis_id),
                            ]
                        ),
                        0,
                    )
                self.assertIn(f"reused={reused}", output.getvalue())
                self.assertIn("coverage_ratio=", output.getvalue())
                self.assertNotIn(self.profile.name, output.getvalue())
                self.assertNotIn("test-only", output.getvalue())

    def test_cli_invalid_import_does_not_connect_or_log_profile(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('{"name":"Sensitive fixture", "extra":"private"}')
            with (
                patch("app.company.create_database_engine") as connect,
                self.assertLogs("app.company", level="ERROR") as logs,
            ):
                self.assertEqual(company_main(["create", "--file", str(path)]), 1)
            connect.assert_not_called()
            self.assertNotIn("Sensitive", str(logs.output))
            self.assertNotIn("private", str(logs.output))
