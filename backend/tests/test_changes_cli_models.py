import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from change_fixtures import ChangeDatabaseMixin, item, output
from sqlalchemy import JSON, delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.changes import main
from app.models import (
    DocumentAnalysisChangeSet,
    Tender,
    TenderAnalysis,
    TenderMetadataChangeSet,
    TenderRevision,
)
from app.scrapers.records import ParsedListing
from app.services.change_detection import compare_document, compare_metadata
from app.services.ingestion import ingest_tenders


class ChangesModelCLITests(ChangeDatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        ingest_tenders(
            self.engine,
            self.source,
            ParsedListing(
                [
                    self.record.model_copy(
                        update={
                            "title": "Changed title",
                            "description": "Synthetic " * 1000,
                        }
                    )
                ]
            ),
        )
        with Session(self.engine) as session:
            self.tender_id = session.scalar(select(Tender.id))
            self.revision_ids = list(
                session.scalars(select(TenderRevision.id).order_by(TenderRevision.id))
            )
        self.document_id = self.add_document(self.tender_id)
        old_version = self.add_version(
            self.document_id, datetime(2026, 9, 1, tzinfo=UTC)
        )
        new_version = self.add_version(
            self.document_id, datetime(2026, 9, 2, tzinfo=UTC)
        )
        self.old_analysis = self.add_analysis(old_version)
        self.new_analysis = self.add_analysis(
            new_version, output(required_documents=[item("Signed declaration")])
        )
        self.document_changes = compare_document(
            self.engine, self.old_analysis, self.new_analysis
        )
        self.metadata_changes = compare_metadata(self.engine, *self.revision_ids)

    def row_data(self, model):
        with Session(self.engine) as session:
            row = session.scalar(select(model))
            return {
                column.name: getattr(row, column.name)
                for column in model.__table__.c
                if column.name != "id"
            }

    def test_json_types_timestamps_and_no_update_columns(self):
        for model in (
            TenderRevision,
            TenderMetadataChangeSet,
            DocumentAnalysisChangeSet,
        ):
            self.assertNotIn("updated_at", model.__table__.c)
            self.assertTrue(model.__table__.c.created_at.type.timezone)
            self.assertIsNotNone(self.row_data(model)["created_at"])
            self.assertTrue(
                all(fk.ondelete == "RESTRICT" for fk in model.__table__.foreign_keys)
            )
            for column in model.__table__.c:
                if isinstance(column.type, JSON):
                    self.assertIsInstance(
                        column.type.dialect_impl(postgresql.dialect()), postgresql.JSONB
                    )
                    self.assertIsInstance(
                        column.type.dialect_impl(sqlite.dialect()), JSON
                    )

    def test_unique_identities_and_revision_index_checks(self):
        for model in (
            TenderRevision,
            TenderMetadataChangeSet,
            DocumentAnalysisChangeSet,
        ):
            with (
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(model(**self.row_data(model)))
        for index in (0, -1):
            with (
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(
                    TenderRevision(
                        **(self.row_data(TenderRevision) | {"revision_index": index})
                    )
                )

    def test_all_foreign_keys_enforced(self):
        for model, keys in (
            (TenderRevision, ("tender_id",)),
            (
                TenderMetadataChangeSet,
                ("tender_id", "from_revision_id", "to_revision_id"),
            ),
            (
                DocumentAnalysisChangeSet,
                ("tender_document_id", "from_analysis_id", "to_analysis_id"),
            ),
        ):
            for key in keys:
                data = self.row_data(model) | {key: 99999}
                if model is TenderRevision:
                    data["revision_index"] = 50
                else:
                    data["changeset_version"] = "new"
                with (
                    self.subTest(model=model, key=key),
                    self.assertRaises(IntegrityError),
                    Session(self.engine) as session,
                    session.begin(),
                ):
                    session.add(model(**data))

    def test_revision_and_analysis_deletion_restrictions(self):
        for model, row_id in (
            (TenderRevision, self.revision_ids[0]),
            (TenderRevision, self.revision_ids[1]),
            (TenderAnalysis, self.old_analysis),
            (TenderAnalysis, self.new_analysis),
        ):
            for orm in (True, False):
                with (
                    self.subTest(model=model, orm=orm),
                    self.assertRaises(IntegrityError),
                    Session(self.engine) as session,
                    session.begin(),
                ):
                    if orm:
                        session.delete(session.get(model, row_id))
                    else:
                        session.execute(delete(model).where(model.id == row_id))

    def test_revision_alone_restricts_tender_delete(self):
        other = self.record.model_validate(
            self.record.model_dump()
            | {"external_id": "other", "source_url": "https://example.test/other"}
        )
        ingest_tenders(self.engine, self.source, ParsedListing([other]))
        with Session(self.engine) as session:
            other_id = session.scalar(
                select(Tender.id).where(Tender.external_id == "other")
            )
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.delete(session.get(Tender, other_id))

    def test_cli_history_metadata_and_document_offline(self):
        commands = [
            ["history", "--tender-id", str(self.tender_id)],
            [
                "metadata",
                "--from-revision-id",
                str(self.revision_ids[0]),
                "--to-revision-id",
                str(self.revision_ids[1]),
            ],
            [
                "document",
                "--from-analysis-id",
                str(self.old_analysis),
                "--to-analysis-id",
                str(self.new_analysis),
            ],
        ]
        with (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only"}, clear=True),
            patch("app.changes.create_database_engine", return_value=self.engine),
            patch.object(self.engine, "dispose"),
        ):
            for command in commands:
                buffer = StringIO()
                with redirect_stdout(buffer):
                    self.assertEqual(main(command), 0)
                text = buffer.getvalue()
                self.assertLess(len(text), 2000)
                self.assertNotIn("Synthetic " * 100, text)
                self.assertNotIn("test-only", text)
                self.assertIn(
                    "revision_index=1" if command[0] == "history" else "reused=true",
                    text,
                )
            with self.assertLogs("app.changes", level="ERROR") as logs:
                self.assertEqual(
                    main(
                        [
                            "document",
                            "--from-analysis-id",
                            str(self.new_analysis),
                            "--to-analysis-id",
                            str(self.old_analysis),
                        ]
                    ),
                    1,
                )
            self.assertIn("precede", str(logs.output))

    def test_change_set_json_round_trip_contains_exact_evidence(self):
        stored = self.snapshot(
            DocumentAnalysisChangeSet, self.document_changes.change_set_id
        )
        self.assertEqual(
            json.loads(json.dumps(stored["changes"]))[0]["new"]["evidence"],
            "Signed declaration",
        )
