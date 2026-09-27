"""Opt-in checks against an already migrated, disposable PostgreSQL database.

No provider/source/broker calls. Normal fixtures roll back. The lock test commits
one explicitly identified test row, then deletes only that row after releasing it.
"""

import os
import unittest
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine
from app.models import (
    Base,
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    PipelineRun,
    Source,
    Tender,
    TenderDocument,
)
from app.rag.chunking import CHUNKER_VERSION
from app.schemas.product import Dashboard, TenderDetail
from app.services import queries


@unittest.skipUnless(
    os.environ.get("TENDERSCOUT_RUN_POSTGRES_TESTS") == "1",
    "PostgreSQL checks require TENDERSCOUT_RUN_POSTGRES_TESTS=1 and a disposable DB",
)
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings(_env_file=None)
        if not (
            cls.settings.postgres_db.startswith("tenderscout_")
            and cls.settings.postgres_db.endswith("_test")
        ):
            raise RuntimeError("Integration DB name must be tenderscout_*_test")
        cls.engine = create_database_engine(cls.settings)
        cls.addClassCleanup(cls.engine.dispose)
        # Opt-in with an unavailable database is a failure, never a silent skip.
        with cls.engine.connect() as connection:
            if (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                != "0007"
            ):
                raise RuntimeError("Apply Alembic head 0007 to the test database first")

    def setUp(self):
        self.connection = self.engine.connect()
        self.addCleanup(self.connection.close)
        self.transaction = self.connection.begin()
        self.addCleanup(self.rollback)
        self.session = Session(self.connection)
        self.addCleanup(self.session.close)

    def rollback(self):
        if self.transaction.is_active:
            self.transaction.rollback()

    def test_migrated_schema_and_vector_type(self):
        self.assertTrue(
            set(Base.metadata.tables) <= set(inspect(self.connection).get_table_names())
        )
        self.assertTrue(
            self.connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension "
                    "WHERE extname = 'vector')"
                )
            )
        )
        self.assertEqual(
            self.connection.scalar(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = 'chunk_embeddings'::regclass "
                    "AND attname = 'embedding'"
                )
            ),
            "vector(1536)",
        )

    def seed_document(self):
        source = Source(
            name="Integration test", slug=str(uuid4()), base_url="https://example.test"
        )
        self.session.add(source)
        self.session.flush()
        deadline = datetime.now(timezone(timedelta(hours=5))) + timedelta(days=1)
        tender = Tender(
            source_id=source.id,
            title="Integration fixture 100%",
            organization="Test only",
            source_url="https://example.test/notice",
            deadline=deadline,
        )
        self.session.add(tender)
        self.session.flush()
        document = TenderDocument(
            tender_id=tender.id, source_url="https://example.test/file.pdf"
        )
        self.session.add(document)
        self.session.flush()
        version = DocumentVersion(
            document_id=document.id,
            content_hash="a" * 64,
            byte_size=10,
            storage_path="test-only/private.pdf",
            extracted_text="private PDF text",
            extraction_status="extracted",
        )
        self.session.add(version)
        self.session.flush()
        return tender, version, deadline

    def test_timezone_and_product_sql_projections(self):
        tender, version, expected_deadline = self.seed_document()
        self.session.expire(tender)
        self.assertIsNotNone(tender.deadline.utcoffset())
        self.assertEqual(
            tender.deadline.astimezone(UTC), expected_deadline.astimezone(UTC)
        )
        page = queries.tenders(self.connection, search="100%", limit=1)
        self.assertEqual(page["items"][0]["id"], tender.id)
        detail = TenderDetail.model_validate(
            queries.tender_detail(self.connection, tender.id, self.settings)
        )
        self.assertEqual(detail.documents.items[0].versions.items[0].id, version.id)
        self.assertNotIn("storage_path", detail.model_dump_json())
        self.assertNotIn("private PDF text", detail.model_dump_json())
        Dashboard.model_validate(queries.dashboard(self.connection))
        self.assertEqual(queries.company_list(self.connection)["items"], [])
        self.assertEqual(queries.runs(self.connection)["items"], [])

    def test_pgvector_distance_and_index_readiness(self):
        _, version, _ = self.seed_document()
        chunk = DocumentChunk(
            document_version_id=version.id,
            chunk_index=0,
            chunker_version=CHUNKER_VERSION,
            chunk_size=self.settings.rag_chunk_size_chars,
            chunk_overlap=self.settings.rag_chunk_overlap_chars,
            content_hash="b" * 64,
            text="Integration fixture",
            start_char=0,
            end_char=19,
        )
        self.session.add(chunk)
        self.session.flush()
        vector = [1.0] + [0.0] * 1535
        self.session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider="openai",
                model="integration-only",
                dimensions=1536,
                input_hash=chunk.content_hash,
                embedding=vector,
            )
        )
        self.session.flush()
        distance = self.session.scalar(
            select(ChunkEmbedding.embedding.cosine_distance(vector))
        )
        self.assertAlmostEqual(distance, 0.0)
        settings = self.settings.model_copy(
            update={"ai_embedding_model": "integration-only"}
        )
        result = queries.version_list(self.connection, version.document_id, settings)
        self.assertTrue(result["items"][0]["is_indexed"])
        settings.rag_chunk_overlap_chars += 1
        self.assertFalse(
            queries.version_list(self.connection, version.document_id, settings)[
                "items"
            ][0]["is_indexed"]
        )

    def test_partial_unique_active_source_index(self):
        def row(status):
            return PipelineRun(
                source_slug="contracts-finder",
                trigger="manual",
                status=status,
                celery_task_id=str(uuid4()),
            )

        first = row("queued")
        self.session.add(first)
        self.session.flush()
        with self.assertRaises(IntegrityError) as raised, self.session.begin_nested():
            self.session.add(row("running"))
            self.session.flush()
        self.assertEqual(
            raised.exception.orig.diag.constraint_name, "uq_pipeline_active_source"
        )
        first.status = "completed"
        self.session.flush()
        self.session.add(row("queued"))
        self.session.flush()

    def test_pipeline_row_lock_excludes_second_connection(self):
        # Separate committed row makes a real conflicting lock visible to connection 2.
        with self.engine.begin() as setup:
            row_id = setup.scalar(
                PipelineRun.__table__.insert()
                .values(
                    source_slug="find-a-tender",
                    trigger="manual",
                    status="completed",
                    celery_task_id=str(uuid4()),
                )
                .returning(PipelineRun.id)
            )
        try:
            self.session.execute(
                select(PipelineRun).where(PipelineRun.id == row_id).with_for_update()
            ).scalar_one()
            with self.engine.connect() as other, other.begin():
                with self.assertRaises(OperationalError) as raised:
                    other.execute(
                        select(PipelineRun.id)
                        .where(PipelineRun.id == row_id)
                        .with_for_update(nowait=True)
                    )
                self.assertEqual(raised.exception.orig.sqlstate, "55P03")
                other.rollback()
        finally:
            self.session.close()
            self.rollback()
            with self.engine.begin() as cleanup:
                cleanup.execute(
                    PipelineRun.__table__.delete().where(PipelineRun.id == row_id)
                )
