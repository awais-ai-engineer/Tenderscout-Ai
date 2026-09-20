import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, create_engine, event, func, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import ENV_FILE, Settings
from app.models import Base, DocumentVersion, Source, Tender, TenderDocument
from app.scrapers.records import DiscoveredDocument
from app.services.document_download import DownloadedDocument
from app.services.documents import persist_version, process_documents, upsert_metadata
from app.services.ingestion import IdentityConflict
from app.services.pdf_text import ExtractionResult

PDF = (Path(__file__).parent / "fixtures" / "tiny_text.pdf").read_bytes()
URL = "https://www.contractsfinder.service.gov.uk/Notice/Attachment/test"


class DocumentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        self.active_transactions = 0

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            self.active_transactions += 1

        @event.listens_for(self.engine, "commit")
        @event.listens_for(self.engine, "rollback")
        def end(connection):
            self.active_transactions -= 1

        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session, session.begin():
            source = Source(
                name="Contracts Finder",
                slug="contracts-finder",
                base_url="https://www.contractsfinder.service.gov.uk",
            )
            tender = Tender(
                source=source,
                external_id="notice-id",
                title="Tender",
                source_url="https://www.contractsfinder.service.gov.uk/Notice/notice-id",
            )
            session.add(tender)
            session.flush()
            self.tender_id = tender.id
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Path(directory.name)
        with patch.dict(os.environ, {}, clear=True):
            self.settings = Settings(
                _env_file=None,
                postgres_password="test-only",
                document_storage_dir=self.storage,
            )
        self.record = DiscoveredDocument(
            tender_external_id="notice-id",
            source_document_id="doc-1",
            title="Specification",
            source_url=URL,
            document_type="biddingDocuments",
            media_type="application/pdf",
        )
        self.now = datetime.now(UTC)

    def changed(self, values: dict) -> DiscoveredDocument:
        return DiscoveredDocument.model_validate(self.record.model_dump() | values)

    def process(self, body: bytes = PDF, records=None, status=200):
        def respond(request):
            self.assertEqual(
                self.active_transactions, 0, "Network held a DB transaction"
            )
            return httpx.Response(
                status,
                stream=httpx.ByteStream(body),
                headers={"Content-Type": "application/pdf"},
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return process_documents(
                self.engine,
                client,
                records if records is not None else [self.record],
                self.settings,
            )

    def test_a_a_b_preserves_logical_identity_files_and_version_history(self) -> None:
        first = self.process()
        self.assertEqual(
            (first.metadata_created, first.versions_created, first.extracted), (1, 1, 1)
        )
        with Session(self.engine) as session:
            first_document = session.scalar(select(TenderDocument))
            first_seen = first_document.first_seen_at
            document_id = first_document.id
            first_version = session.scalar(select(DocumentVersion))
            original = (
                first_version.id,
                first_version.content_hash,
                first_version.storage_path,
                first_version.extracted_text,
            )
        with patch(
            "app.services.documents.extract_pdf",
            side_effect=AssertionError("Unchanged hash re-extracted"),
        ):
            second = self.process()
        self.assertEqual(
            (
                second.metadata_unchanged,
                second.content_unchanged,
                second.versions_created,
            ),
            (1, 1, 0),
        )
        changed_body = PDF.replace(b"page one", b"page NEW")
        third = self.process(changed_body)
        self.assertEqual(
            (third.metadata_unchanged, third.versions_created, third.extracted),
            (1, 1, 1),
        )
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(TenderDocument)), 1
            )
            document = session.get(TenderDocument, document_id)
            self.assertEqual(document.first_seen_at, first_seen)
            self.assertGreaterEqual(document.last_seen_at, first_seen)
            versions = session.scalars(
                select(DocumentVersion).order_by(DocumentVersion.id)
            ).all()
            self.assertEqual(len(versions), 2)
            self.assertEqual(
                (
                    versions[0].id,
                    versions[0].content_hash,
                    versions[0].storage_path,
                    versions[0].extracted_text,
                ),
                original,
            )
            self.assertNotEqual(versions[0].content_hash, versions[1].content_hash)
            self.assertIn("page NEW", versions[1].extracted_text)
            for version, expected in zip(versions, [PDF, changed_body], strict=True):
                self.assertEqual(
                    version.storage_path,
                    f"{version.content_hash[:2]}/{version.content_hash}.pdf",
                )
                self.assertEqual(
                    (self.storage / version.storage_path).read_bytes(), expected
                )
                self.assertEqual(version.document_id, document_id)

    def test_failed_extraction_preserves_raw_version(self) -> None:
        body = b"%PDF-1.4\nbroken structure\n%%EOF"
        result = self.process(body)
        self.assertEqual(
            (result.versions_created, result.failed, result.extracted), (1, 1, 0)
        )
        with Session(self.engine) as session:
            version = session.scalar(select(DocumentVersion))
            self.assertEqual(version.extraction_status, "failed")
            self.assertIsNone(version.extracted_text)
            self.assertLess(len(version.extraction_error), 100)
            self.assertEqual((self.storage / version.storage_path).read_bytes(), body)

    def test_sparse_metadata_preserves_known_values_and_first_seen(self) -> None:
        created = upsert_metadata(self.engine, self.record, self.now)
        sparse = DiscoveredDocument(tender_external_id="notice-id", source_url=URL)
        observed = self.now + timedelta(hours=1)
        unchanged = upsert_metadata(self.engine, sparse, observed)
        self.assertEqual(unchanged.outcome, "unchanged")
        with Session(self.engine) as session:
            document = session.get(TenderDocument, created.document_id)
            self.assertEqual(document.title, "Specification")
            self.assertEqual(document.source_document_id, "doc-1")
            self.assertEqual(document.media_type, "application/pdf")
            # SQLite does not retain timezone offsets; only compare instants here.
            self.assertEqual(document.first_seen_at.replace(tzinfo=UTC), self.now)
            self.assertEqual(document.last_seen_at.replace(tzinfo=UTC), observed)

    def test_source_id_tracks_url_changes_and_url_fallback_enriches_id(self) -> None:
        sparse = DiscoveredDocument(tender_external_id="notice-id", source_url=URL)
        first = upsert_metadata(self.engine, sparse, self.now)
        enriched = upsert_metadata(self.engine, self.record, self.now)
        moved = upsert_metadata(
            self.engine,
            self.changed({"source_url": URL + "-new", "title": "Revised"}),
            self.now,
        )
        self.assertEqual(
            {first.document_id, enriched.document_id, moved.document_id},
            {first.document_id},
        )
        self.assertEqual(
            (first.outcome, enriched.outcome, moved.outcome),
            ("created", "changed", "changed"),
        )

    def test_two_identity_matches_and_url_reuse_are_rejected_without_mutation(
        self,
    ) -> None:
        first = upsert_metadata(self.engine, self.record, self.now)
        other = self.changed(
            {"source_document_id": "doc-2", "source_url": URL + "-other"}
        )
        upsert_metadata(self.engine, other, self.now)
        conflicts = [
            self.changed({"source_url": str(other.source_url)}),
            self.changed({"source_document_id": "doc-3"}),
        ]
        for conflict in conflicts:
            with self.assertRaises(IdentityConflict):
                upsert_metadata(self.engine, conflict, self.now + timedelta(hours=1))
        with Session(self.engine) as session:
            self.assertEqual(
                session.get(TenderDocument, first.document_id).source_url, URL
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(TenderDocument)), 2
            )

    def test_missing_parent_and_wrong_source_skip_without_download(self) -> None:
        with Session(self.engine) as session, session.begin():
            source = Source(name="Other", slug="other", base_url="https://example.com")
            session.add(
                Tender(
                    source=source,
                    external_id="other-notice",
                    title="Other",
                    source_url="https://example.com/other",
                )
            )
        for identity in ("missing", "other-notice"):
            record = self.changed({"tender_external_id": identity})
            with (
                patch(
                    "app.services.documents.download_pdf",
                    side_effect=AssertionError("Missing parent downloaded"),
                ),
                self.assertLogs("app.services.documents", level="WARNING") as logs,
            ):
                result = self.process(records=[record])
            self.assertEqual(result.skipped, 1)
            self.assertIn("ingest tenders first", " ".join(logs.output))
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(TenderDocument)), 0
            )

    def test_unsupported_and_external_documents_keep_metadata_only(self) -> None:
        external = self.changed(
            {
                "source_url": "https://external.example/a.pdf",
                "source_document_id": "external",
            }
        )
        nonpdf = self.changed({"media_type": "application/zip"})
        with patch(
            "app.services.documents.download_pdf",
            side_effect=AssertionError("Unsupported document downloaded"),
        ):
            result = self.process(records=[external, nonpdf])
        self.assertEqual(
            (result.metadata_created, result.skipped, result.versions_created),
            (2, 2, 0),
        )

    def test_download_failure_keeps_metadata_without_version_and_continues(
        self,
    ) -> None:
        result = self.process(status=403)
        self.assertEqual(
            (result.metadata_created, result.failed, result.versions_created), (1, 1, 0)
        )
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(DocumentVersion)), 0
            )
        self.assertEqual(list(self.storage.rglob("*.pdf")), [])

    def test_final_version_transaction_rechecks_hash(self) -> None:
        self.process()
        with Session(self.engine) as session:
            original = session.scalar(select(DocumentVersion))
            downloaded = DownloadedDocument(
                original.content_hash,
                original.byte_size,
                original.media_type,
                original.storage_path,
                self.now,
            )
            document_id = original.document_id
        self.assertFalse(
            persist_version(
                self.engine,
                document_id,
                downloaded,
                ExtractionResult("failed", error="Must not overwrite"),
            )
        )
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(DocumentVersion.extraction_status)), "extracted"
            )

    def test_extraction_runs_outside_database_transaction(self) -> None:
        def extract(path, max_pages):
            self.assertEqual(self.active_transactions, 0)
            return ExtractionResult("empty")

        with patch("app.services.documents.extract_pdf", side_effect=extract):
            result = self.process()
        self.assertEqual(
            (result.versions_created, result.empty, result.failed), (1, 1, 0)
        )

    def test_database_failure_is_sanitized_and_does_not_download(self) -> None:
        with (
            patch(
                "app.services.documents.upsert_metadata",
                side_effect=OperationalError("query", {}, RuntimeError("secret")),
            ),
            patch("app.services.documents.download_pdf") as download,
            self.assertLogs("app.services.documents", level="ERROR") as logs,
        ):
            result = self.process()
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.metadata_created, 0)
        download.assert_not_called()
        self.assertNotIn("secret", " ".join(logs.output))

    def test_tender_delete_restricted_and_document_delete_cascades(self) -> None:
        self.process()
        with Session(self.engine) as session:
            tender = session.get(Tender, self.tender_id)
            self.assertEqual(len(tender.documents), 1)
            session.delete(tender)
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
            document = session.scalar(select(TenderDocument))
            self.assertEqual(len(document.versions), 1)
            session.delete(document)
            session.commit()
            self.assertEqual(
                session.scalar(select(func.count()).select_from(DocumentVersion)), 0
            )
            self.assertIsNotNone(session.get(Tender, self.tender_id))

    def test_database_document_delete_cascades_without_orm(self) -> None:
        self.process()
        with self.engine.begin() as connection:
            connection.execute(TenderDocument.__table__.delete())
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(DocumentVersion)), 0
            )

    def test_positive_size_and_status_constraints_are_enforced(self) -> None:
        self.process()
        for values in ({"byte_size": 0}, {"extraction_status": "unknown"}):
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                self.engine.begin() as connection,
            ):
                connection.execute(DocumentVersion.__table__.update().values(**values))

    def test_document_uniqueness_and_nullable_ids(self) -> None:
        first = upsert_metadata(self.engine, self.record, self.now)
        for values in (
            {"source_url": URL, "source_document_id": "another"},
            {"source_url": URL + "-other", "source_document_id": "doc-1"},
        ):
            with (
                self.subTest(values=values),
                Session(self.engine) as session,
                self.assertRaises(IntegrityError),
                session.begin(),
            ):
                session.add(TenderDocument(tender_id=self.tender_id, **values))
        with Session(self.engine) as session, session.begin():
            for suffix in ("-null-a", "-null-b"):
                session.add(
                    TenderDocument(tender_id=self.tender_id, source_url=URL + suffix)
                )
        self.assertIsNotNone(first)

    def test_version_hash_uniqueness_is_enforced(self) -> None:
        self.process()
        with Session(self.engine) as session:
            version = session.scalar(select(DocumentVersion))
            session.add(
                DocumentVersion(
                    document_id=version.document_id,
                    content_hash=version.content_hash,
                    byte_size=1,
                    storage_path="irrelevant",
                    extraction_status="empty",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()


class DocumentSchemaTests(unittest.TestCase):
    def test_document_limits_must_be_positive(self) -> None:
        for field in ("document_max_bytes", "document_max_pages"):
            for value in (0, -1):
                with (
                    self.subTest(field=field, value=value),
                    patch.dict(os.environ, {}, clear=True),
                    self.assertRaises(ValidationError),
                ):
                    Settings(
                        _env_file=None, postgres_password="test-only", **{field: value}
                    )

    def test_foreign_keys_indexes_relationships_and_checks(self) -> None:
        for model, target, deletion, index in (
            (TenderDocument, "tenders.id", "RESTRICT", "ix_tender_documents_tender_id"),
            (
                DocumentVersion,
                "tender_documents.id",
                "CASCADE",
                "ix_document_versions_document_id",
            ),
        ):
            foreign_key = next(iter(model.__table__.foreign_keys))
            self.assertEqual(foreign_key.target_fullname, target)
            self.assertEqual(foreign_key.ondelete, deletion)
            self.assertIsNotNone(foreign_key.constraint.name)
            self.assertEqual({item.name for item in model.__table__.indexes}, {index})
        self.assertEqual(DocumentVersion.__table__.c.content_hash.type.length, 64)
        self.assertEqual(
            {
                constraint.name
                for constraint in DocumentVersion.__table__.constraints
                if isinstance(constraint, CheckConstraint)
            },
            {"ck_versions_positive_size", "ck_versions_extraction_status"},
        )
        self.assertEqual(inspect(Tender).relationships.documents.passive_deletes, "all")
        self.assertNotIn("delete", inspect(Tender).relationships.documents.cascade)
        self.assertTrue(inspect(TenderDocument).relationships.versions.passive_deletes)
        self.assertIn("delete", inspect(TenderDocument).relationships.versions.cascade)
        self.assertEqual(
            inspect(DocumentVersion).relationships.document.back_populates, "versions"
        )

    def test_document_settings_defaults_and_environment(self) -> None:
        with patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only"}, clear=True):
            settings = Settings(_env_file=None)
            self.assertEqual(
                settings.document_storage_dir, ENV_FILE.parent / ".data/documents"
            )
            self.assertEqual(settings.document_max_bytes, 26214400)
            self.assertEqual(settings.document_max_pages, 500)
        with patch.dict(
            os.environ,
            {
                "POSTGRES_PASSWORD": "test-only",
                "DOCUMENT_MAX_BYTES": "100",
                "DOCUMENT_MAX_PAGES": "2",
                "DOCUMENT_STORAGE_DIR": ".data/other",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)
            self.assertEqual(
                (settings.document_max_bytes, settings.document_max_pages), (100, 2)
            )
            self.assertEqual(
                settings.document_storage_dir, ENV_FILE.parent / ".data/other"
            )
