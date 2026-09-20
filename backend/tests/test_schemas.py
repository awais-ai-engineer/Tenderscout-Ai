import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.models import Source, Tender
from app.schemas import SourceCreate, SourceRead, TenderCreate, TenderRead


class SchemaTests(unittest.TestCase):
    def test_valid_create_inputs(self) -> None:
        source = SourceCreate(
            name=" Public Procurement ",
            slug="public-procurement",
            base_url="https://procurement.example.org",
        )
        self.assertEqual(source.name, "Public Procurement")
        self.assertTrue(source.is_active)
        tender = TenderCreate(
            source_id=1,
            title="Network equipment",
            source_url="https://procurement.example.org/tenders/123",
            deadline="2026-10-01T12:00:00+05:00",
            content_hash="a" * 64,
        )
        self.assertIsNotNone(tender.deadline.utcoffset())
        self.assertIsNone(tender.external_id)

    def test_missing_required_fields_are_rejected(self) -> None:
        examples = (
            (
                SourceCreate,
                {
                    "name": "Public Procurement",
                    "slug": "public-procurement",
                    "base_url": "https://procurement.example.org",
                },
            ),
            (
                TenderCreate,
                {
                    "source_id": 1,
                    "title": "Network equipment",
                    "source_url": "https://procurement.example.org/tenders/123",
                },
            ),
        )
        for schema, values in examples:
            for field in values:
                with self.subTest(schema=schema.__name__, field=field):
                    incomplete = {
                        key: value for key, value in values.items() if key != field
                    }
                    with self.assertRaises(ValidationError):
                        schema.model_validate(incomplete)

    def test_invalid_tender_fields_are_rejected(self) -> None:
        valid = {
            "source_id": 1,
            "title": "Network equipment",
            "source_url": "https://procurement.example.org/tenders/123",
        }
        for invalid in (
            {"title": "  "},
            {"source_id": 0},
            {"source_url": "not-a-url"},
            {"deadline": "2026-10-01T12:00:00"},
            {"content_hash": "not-a-digest"},
            {"external_id": ""},
            {"unexpected": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TenderCreate.model_validate(valid | invalid)

    def test_invalid_source_fields_are_rejected(self) -> None:
        valid = {
            "name": "Public Procurement",
            "slug": "public-procurement",
            "base_url": "https://procurement.example.org",
        }
        for invalid in (
            {"name": "  "},
            {"slug": ""},
            {"slug": "Not a slug"},
            {"base_url": "ftp://procurement.example.org"},
            {"unexpected": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                SourceCreate.model_validate(valid | invalid)

    def test_read_schemas_accept_orm_entities(self) -> None:
        timestamp = datetime(2026, 9, 20, tzinfo=UTC)
        source = Source(
            id=1,
            name="Public Procurement",
            slug="public-procurement",
            base_url="https://procurement.example.org",
            is_active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
        tender = Tender(
            id=2,
            source_id=1,
            title="Network equipment",
            source_url="https://procurement.example.org/tenders/123",
            first_seen_at=timestamp,
            last_seen_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.assertEqual(SourceRead.model_validate(source).id, source.id)
        output = TenderRead.model_validate(tender)
        self.assertEqual(output.source_id, source.id)
        self.assertEqual(output.first_seen_at, timestamp)
        self.assertIsNone(output.external_id)
