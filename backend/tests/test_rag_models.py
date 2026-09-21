import unittest

from pgvector.sqlalchemy import VECTOR
from rag_fixtures import CHUNKING, EMBEDDING, RagDatabaseMixin
from sqlalchemy import JSON, delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    TenderDocument,
    TenderQuestion,
)
from app.services.indexing import index_document
from app.services.qa import ask_tender


class RagModelTests(RagDatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        index_document(
            self.engine,
            self.version_id,
            self.embedder,
            embedding=EMBEDDING,
            chunking=CHUNKING,
        )
        ask_tender(
            self.engine,
            self.version_id,
            "Deadline?",
            self.embedder,
            self.answerer,
            embedding=EMBEDDING,
            answer_model="test-answer",
        )

    def row_data(self, model):
        with Session(self.engine) as session:
            row = session.scalar(select(model))
            return {
                column.name: getattr(row, column.name)
                for column in model.__table__.c
                if column.name != "id"
            }

    def test_real_vector_type_json_variant_and_aware_immutable_timestamps(self):
        vector_type = ChunkEmbedding.__table__.c.embedding.type
        self.assertIsInstance(vector_type.dialect_impl(postgresql.dialect()), VECTOR)
        self.assertEqual(vector_type.dim, 1536)
        self.assertIsInstance(vector_type.dialect_impl(sqlite.dialect()), JSON)
        self.assertIsInstance(
            TenderQuestion.__table__.c.citations.type.dialect_impl(
                postgresql.dialect()
            ),
            postgresql.JSONB,
        )
        for model in (DocumentChunk, ChunkEmbedding, TenderQuestion):
            self.assertNotIn("updated_at", model.__table__.c)
            self.assertTrue(model.__table__.c.created_at.type.timezone)
            self.assertIsNotNone(self.row_data(model)["created_at"])
            self.assertTrue(
                all(fk.ondelete == "RESTRICT" for fk in model.__table__.foreign_keys)
            )

    def test_unique_identities_and_foreign_keys(self):
        for model, foreign_key in (
            (DocumentChunk, "document_version_id"),
            (ChunkEmbedding, "chunk_id"),
            (TenderQuestion, "document_version_id"),
        ):
            data = self.row_data(model)
            for changes in ({}, {foreign_key: 99999}):
                with (
                    self.subTest(model=model, changes=changes),
                    self.assertRaises(IntegrityError),
                    Session(self.engine) as session,
                    session.begin(),
                ):
                    session.add(model(**(data | changes)))

    def test_check_constraints(self):
        chunk = self.row_data(DocumentChunk) | {"chunker_version": "v2"}
        for changes in (
            {"chunk_index": -1},
            {"start_char": -1},
            {"end_char": 0},
            {"chunk_overlap": 2000},
        ):
            with (
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(DocumentChunk(**(chunk | changes)))
        embedding = self.row_data(ChunkEmbedding) | {
            "model": "different",
            "dimensions": 3,
        }
        with (
            self.assertRaises(IntegrityError),
            Session(self.engine) as session,
            session.begin(),
        ):
            session.add(ChunkEmbedding(**embedding))
        question = self.row_data(TenderQuestion) | {"answer_model": "different"}
        for changes in (
            {"top_k": 0},
            {"status": "winner"},
            {"embedding_dimensions": 3},
        ):
            with (
                self.assertRaises(IntegrityError),
                Session(self.engine) as session,
                session.begin(),
            ):
                session.add(TenderQuestion(**(question | changes)))

    def test_deletion_restricts_version_logical_document_and_embedded_chunk(self):
        with Session(self.engine) as session:
            document_id = session.get(DocumentVersion, self.version_id).document_id
            chunk_id = session.scalar(select(DocumentChunk.id))
        for model, row_id in (
            (DocumentVersion, self.version_id),
            (TenderDocument, document_id),
            (DocumentChunk, chunk_id),
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
                        if model is TenderDocument:
                            self.assertTrue(row.versions)
                        session.delete(row)
                    else:
                        session.execute(delete(model).where(model.id == row_id))
