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
                "company_profiles",
                "company_capabilities",
                "company_certifications",
                "company_experience",
                "tender_matches",
                "document_chunks",
                "chunk_embeddings",
                "tender_questions",
                "tender_revisions",
                "tender_metadata_change_sets",
                "document_analysis_change_sets",
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
        required.update(
            {
                "company_profiles": {
                    "id",
                    "name",
                    "capabilities_complete",
                    "certifications_complete",
                    "experience_complete",
                    "financials_complete",
                    "created_at",
                    "updated_at",
                },
                "company_capabilities": {
                    "id",
                    "company_id",
                    "name",
                    "name_key",
                    "created_at",
                },
                "company_certifications": {"id", "company_id", "name", "created_at"},
                "company_experience": {"id", "company_id", "created_at"},
                "tender_matches": {
                    "id",
                    "company_id",
                    "tender_analysis_id",
                    "matcher_version",
                    "eligibility_status",
                    "coverage_ratio",
                    "company_snapshot",
                    "hard_blockers",
                    "matched_requirements",
                    "unmatched_requirements",
                    "unknown_requirements",
                    "capability_matches",
                    "certification_matches",
                    "experience_matches",
                    "risks",
                    "created_at",
                },
            }
        )
        optional.update(
            {
                "company_profiles": {
                    "description",
                    "country",
                    "website",
                    "employee_count",
                    "annual_revenue",
                    "currency",
                    "years_in_business",
                },
                "company_capabilities": {"description"},
                "company_certifications": {
                    "issuer",
                    "identifier",
                    "valid_from",
                    "valid_until",
                },
                "company_experience": {
                    "title",
                    "client",
                    "description",
                    "country",
                    "contract_value",
                    "currency",
                    "started_at",
                    "completed_at",
                },
                "tender_matches": {"score"},
            }
        )
        required.update(
            {
                "document_chunks": {
                    "id",
                    "document_version_id",
                    "chunk_index",
                    "chunker_version",
                    "chunk_size",
                    "chunk_overlap",
                    "content_hash",
                    "text",
                    "start_char",
                    "end_char",
                    "created_at",
                },
                "chunk_embeddings": {
                    "id",
                    "chunk_id",
                    "provider",
                    "model",
                    "dimensions",
                    "embedding",
                    "input_hash",
                    "created_at",
                },
                "tender_questions": {
                    "id",
                    "document_version_id",
                    "question",
                    "question_hash",
                    "embedding_provider",
                    "embedding_model",
                    "embedding_dimensions",
                    "answer_provider",
                    "answer_model",
                    "chunker_version",
                    "retrieval_version",
                    "answer_prompt_version",
                    "top_k",
                    "max_context_chars",
                    "context_hash",
                    "retrieval_succeeded",
                    "context_chunk_ids",
                    "status",
                    "citations",
                    "created_at",
                },
            }
        )
        optional.update(
            {
                "document_chunks": set(),
                "chunk_embeddings": set(),
                "tender_questions": {"answer", "failure_reason"},
            }
        )
        required.update(
            {
                "tender_revisions": {
                    "id",
                    "tender_id",
                    "revision_index",
                    "snapshot_hash",
                    "title",
                    "source_url",
                    "observed_at",
                    "created_at",
                },
                "tender_metadata_change_sets": {
                    "id",
                    "tender_id",
                    "from_revision_id",
                    "to_revision_id",
                    "changeset_version",
                    "has_changes",
                    "change_count",
                    "changed_fields",
                    "changes",
                    "created_at",
                },
                "document_analysis_change_sets": {
                    "id",
                    "tender_document_id",
                    "from_analysis_id",
                    "to_analysis_id",
                    "changeset_version",
                    "has_changes",
                    "change_count",
                    "category_counts",
                    "changes",
                    "created_at",
                },
            }
        )
        optional.update(
            {
                "tender_revisions": {
                    "external_id",
                    "organization",
                    "description",
                    "category",
                    "location",
                    "published_at",
                    "deadline",
                    "source_content_hash",
                },
                "tender_metadata_change_sets": set(),
                "document_analysis_change_sets": set(),
            }
        )
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
                "uq_revisions_index": ("tender_id", "revision_index"),
                "uq_metadata_changes_identity": (
                    "from_revision_id",
                    "to_revision_id",
                    "changeset_version",
                ),
                "uq_document_changes_identity": (
                    "from_analysis_id",
                    "to_analysis_id",
                    "changeset_version",
                ),
                "uq_chunks_identity": (
                    "document_version_id",
                    "chunker_version",
                    "chunk_index",
                ),
                "uq_embeddings_identity": (
                    "chunk_id",
                    "provider",
                    "model",
                    "dimensions",
                    "input_hash",
                ),
                "uq_questions_identity": (
                    "document_version_id",
                    "question_hash",
                    "embedding_provider",
                    "embedding_model",
                    "embedding_dimensions",
                    "answer_provider",
                    "answer_model",
                    "chunker_version",
                    "retrieval_version",
                    "answer_prompt_version",
                    "top_k",
                    "max_context_chars",
                    "context_hash",
                    "retrieval_succeeded",
                ),
                "uq_capabilities_company_name": ("company_id", "name_key"),
                "uq_matches_identity": (
                    "company_id",
                    "tender_analysis_id",
                    "matcher_version",
                ),
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
            if table.name in {
                "sources",
                "tenders",
                "tender_documents",
                "company_profiles",
            }:
                self.assertEqual(str(table.c.updated_at.onupdate.arg), "now()")
        self.assertIsNone(Tender.__table__.c.last_seen_at.onupdate)
        self.assertEqual(str(Source.__table__.c.is_active.server_default.arg), "true")
