import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Source, Tender
from app.schemas.source import SourceCreate
from app.scrapers.records import ParsedListing, ScrapedTender
from app.services.ingestion import InactiveSourceError, ingest_tenders


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.source = SourceCreate(
            name="Test source", slug="test-source", base_url="https://example.org"
        )
        self.record = ScrapedTender(
            external_id="tender-1",
            title="Equipment supply",
            source_url="https://example.org/notices/1",
            organization="Test buyer",
            deadline=datetime(2026, 10, 1, 12, tzinfo=UTC),
        )

    def test_second_run_updates_without_duplicates_and_preserves_first_seen(
        self,
    ) -> None:
        first_time = datetime(2026, 9, 20, 8, tzinfo=UTC)
        second_time = datetime(2026, 9, 20, 9, tzinfo=UTC)
        listing = ParsedListing([self.record], failed=1, skipped=2)
        with patch("app.services.ingestion.datetime") as clock:
            clock.now.return_value = first_time
            first = ingest_tenders(self.engine, self.source, listing)
            clock.now.return_value = second_time
            second = ingest_tenders(self.engine, self.source, listing)
        self.assertEqual(
            (
                first.discovered,
                first.created,
                first.updated,
                first.failed,
                first.skipped,
            ),
            (4, 1, 0, 1, 2),
        )
        self.assertEqual((second.created, second.updated, second.failed), (0, 1, 1))
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Source)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Tender)), 1
            )
            tender = session.scalars(select(Tender)).one()
            # SQLite drops timezone offsets; this checks observation times only.
            self.assertEqual(tender.first_seen_at.replace(tzinfo=UTC), first_time)
            self.assertEqual(tender.last_seen_at.replace(tzinfo=UTC), second_time)
            self.assertIsNone(tender.content_hash)
            source = session.scalars(select(Source)).one()
            self.assertEqual(source.last_scraped_at.replace(tzinfo=UTC), second_time)

    def test_external_id_tracks_url_and_content_changes(self) -> None:
        ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        with Session(self.engine) as session:
            original = session.scalars(select(Tender)).one()
            original_id, created_at, first_seen = (
                original.id,
                original.created_at,
                original.first_seen_at,
            )
        changed = ScrapedTender.model_validate(
            self.record.model_dump()
            | {
                "title": "Updated equipment supply",
                "source_url": "https://example.org/notices/revised",
                "deadline": datetime(2026, 10, 2, 12, tzinfo=UTC),
            }
        )
        result = ingest_tenders(self.engine, self.source, ParsedListing([changed]))
        self.assertEqual((result.created, result.updated), (0, 1))
        with Session(self.engine) as session:
            tender = session.scalars(select(Tender)).one()
            self.assertEqual(
                (tender.id, tender.created_at, tender.first_seen_at),
                (original_id, created_at, first_seen),
            )
            self.assertEqual(tender.source_url, str(changed.source_url))
            self.assertEqual(tender.title, changed.title)
            self.assertEqual(tender.deadline.day, 2)

    def test_url_fallback_promotes_id_and_missing_values_preserve_known_fields(
        self,
    ) -> None:
        without_id = self.record.model_copy(update={"external_id": None})
        first = ingest_tenders(self.engine, self.source, ParsedListing([without_id]))
        second = ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        sparse = ScrapedTender(
            title=self.record.title, source_url=self.record.source_url
        )
        third = ingest_tenders(self.engine, self.source, ParsedListing([sparse]))
        self.assertEqual((first.created, second.updated, third.updated), (1, 1, 1))
        with Session(self.engine) as session:
            tender = session.scalars(select(Tender)).one()
            self.assertEqual(tender.external_id, self.record.external_id)
            self.assertEqual(tender.organization, self.record.organization)
            self.assertIsNotNone(tender.deadline)

    def test_identity_is_scoped_to_source(self) -> None:
        another_source = SourceCreate(
            name="Other test source",
            slug="other-source",
            base_url="https://example.org",
        )
        ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        result = ingest_tenders(
            self.engine, another_source, ParsedListing([self.record])
        )
        self.assertEqual(result.created, 1)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Tender)), 2
            )

    def test_conflicting_keys_are_isolated_without_merging_history(self) -> None:
        other = ScrapedTender(
            external_id="tender-2",
            title="Other equipment",
            source_url="https://example.org/notices/2",
        )
        ingest_tenders(self.engine, self.source, ParsedListing([self.record, other]))
        conflicted = self.record.model_copy(update={"source_url": other.source_url})
        valid = ScrapedTender(
            external_id="tender-3",
            title="Third tender",
            source_url="https://example.org/notices/3",
        )
        with self.assertLogs("app.services.ingestion", level="WARNING"):
            result = ingest_tenders(
                self.engine, self.source, ParsedListing([conflicted, valid])
            )
        self.assertEqual((result.created, result.updated, result.failed), (1, 0, 1))
        with Session(self.engine) as session:
            tenders = session.scalars(select(Tender).order_by(Tender.id)).all()
            self.assertEqual(len(tenders), 3)
            self.assertEqual(tenders[0].source_url, str(self.record.source_url))
            self.assertEqual(tenders[1].external_id, other.external_id)

    def test_url_with_a_different_non_null_id_is_rejected(self) -> None:
        ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        conflicted = self.record.model_copy(update={"external_id": "different"})
        with self.assertLogs("app.services.ingestion", level="WARNING"):
            result = ingest_tenders(
                self.engine, self.source, ParsedListing([conflicted])
            )
        self.assertEqual((result.created, result.updated, result.failed), (0, 0, 1))

    def test_repeated_record_in_one_batch_cannot_create_duplicates(self) -> None:
        result = ingest_tenders(
            self.engine, self.source, ParsedListing([self.record, self.record])
        )
        self.assertEqual((result.created, result.updated), (1, 1))
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Tender)), 1
            )

    def test_database_failure_rolls_back_source_and_all_tenders(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TRIGGER reject_tender BEFORE INSERT ON tenders "
                    "WHEN NEW.title = 'Rejected by test constraint' "
                    "BEGIN SELECT RAISE(ABORT, 'test database rejection'); END"
                )
            )
        rejected = ScrapedTender(
            title="Rejected by test constraint",
            source_url="https://example.org/rejected",
        )
        with (
            self.assertLogs("app.services.ingestion", level="ERROR"),
            self.assertRaises(IntegrityError),
        ):
            ingest_tenders(
                self.engine, self.source, ParsedListing([self.record, rejected])
            )
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Tender)), 0
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Source)), 0
            )

    def test_inactive_source_is_not_reactivated(self) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(
                Source(
                    name=self.source.name,
                    slug=self.source.slug,
                    base_url=str(self.source.base_url),
                    is_active=False,
                )
            )
        with self.assertRaises(InactiveSourceError):
            ingest_tenders(self.engine, self.source, ParsedListing([self.record]))
        with Session(self.engine) as session:
            source = session.scalars(select(Source)).one()
            self.assertFalse(source.is_active)
            self.assertIsNone(source.last_scraped_at)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Tender)), 0
            )
