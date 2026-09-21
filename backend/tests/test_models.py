import unittest

from sqlalchemy import DateTime, UniqueConstraint, inspect

from app.models import Base, Source, Tender


class ModelTests(unittest.TestCase):
    def test_tables_and_nullability(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "sources",
                "tenders",
                "tender_documents",
                "document_versions",
                "tender_analyses",
            },
        )
        required = {
            "sources": {
                "id",
                "name",
                "slug",
                "base_url",
                "is_active",
                "created_at",
                "updated_at",
            },
            "tenders": {
                "id",
                "source_id",
                "title",
                "source_url",
                "first_seen_at",
                "last_seen_at",
                "created_at",
                "updated_at",
            },
            "tender_documents": {
                "id",
                "tender_id",
                "source_url",
                "first_seen_at",
                "last_seen_at",
                "created_at",
                "updated_at",
            },
            "document_versions": {
                "id",
                "document_id",
                "content_hash",
                "byte_size",
                "storage_path",
                "downloaded_at",
                "extraction_status",
                "created_at",
            },
            "tender_analyses": {
                "id",
                "document_version_id",
                "analysis_schema_version",
                "provider",
                "model",
                "prompt_version",
                "input_hash",
                "status",
                "created_at",
            },
        }
        optional = {
            "sources": {"last_scraped_at"},
            "tenders": {
                "external_id",
                "organization",
                "description",
                "category",
                "location",
                "published_at",
                "deadline",
                "content_hash",
            },
            "tender_documents": {
                "source_document_id",
                "title",
                "document_type",
                "media_type",
            },
            "document_versions": {"media_type", "extracted_text", "extraction_error"},
            "tender_analyses": {
                "raw_response",
                "failure_reason",
                "summary",
                "summary_evidence",
                "eligibility_requirements",
                "required_documents",
                "technical_requirements",
                "financial_requirements",
                "submission_instructions",
                "evaluation_criteria",
                "important_dates",
                "contact_information",
                "risks_or_ambiguities",
            },
        }
        for name, table in Base.metadata.tables.items():
            with self.subTest(table=name):
                self.assertEqual(
                    {column.name for column in table.c if not column.nullable},
                    required[name],
                )
                self.assertEqual(
                    {column.name for column in table.c if column.nullable},
                    optional[name],
                )
        self.assertEqual(Tender.__table__.c.content_hash.type.length, 64)

    def test_uniqueness_and_indexes(self) -> None:
        constraints = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertEqual(
            constraints,
            {
                "uq_sources_slug": ("slug",),
                "uq_tenders_source_external_id": ("source_id", "external_id"),
                "uq_tenders_source_url": ("source_id", "source_url"),
                "uq_documents_tender_url": ("tender_id", "source_url"),
                "uq_documents_tender_source_id": ("tender_id", "source_document_id"),
                "uq_versions_document_hash": ("document_id", "content_hash"),
                "uq_analyses_identity": (
                    "document_version_id",
                    "analysis_schema_version",
                    "provider",
                    "model",
                    "prompt_version",
                    "input_hash",
                ),
            },
        )
        self.assertEqual(
            {
                index.name: tuple(index.columns.keys())
                for index in Tender.__table__.indexes
            },
            {
                "ix_tenders_source_id": ("source_id",),
                "ix_tenders_deadline": ("deadline",),
            },
        )

    def test_source_delete_preserves_tender_history(self) -> None:
        foreign_keys = list(Tender.__table__.foreign_keys)
        self.assertEqual(len(foreign_keys), 1)
        self.assertEqual(foreign_keys[0].target_fullname, "sources.id")
        self.assertEqual(foreign_keys[0].ondelete, "RESTRICT")
        self.assertEqual(
            foreign_keys[0].constraint.name, "fk_tenders_source_id_sources"
        )
        relationship = inspect(Source).relationships["tenders"]
        self.assertEqual(relationship.passive_deletes, "all")
        self.assertNotIn("delete", relationship.cascade)
        self.assertNotIn("delete-orphan", relationship.cascade)
        self.assertEqual(relationship.back_populates, "source")
        self.assertEqual(
            inspect(Tender).relationships["source"].back_populates, "tenders"
        )

    def test_timestamp_types_and_defaults(self) -> None:
        for table in Base.metadata.tables.values():
            for column in table.c:
                if isinstance(column.type, DateTime):
                    with self.subTest(table=table.name, column=column.name):
                        self.assertTrue(column.type.timezone)
                        if not column.nullable:
                            self.assertEqual(str(column.server_default.arg), "now()")
            if table.name not in {"document_versions", "tender_analyses"}:
                self.assertEqual(str(table.c.updated_at.onupdate.arg), "now()")
        self.assertIsNone(Tender.__table__.c.last_seen_at.onupdate)
        self.assertEqual(str(Source.__table__.c.is_active.server_default.arg), "true")
