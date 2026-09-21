import unittest

from rag_fixtures import (
    CHUNKING,
    EMBEDDING,
    FakeEmbeddingClient,
    RagDatabaseMixin,
    vector,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import ProviderError
from app.models import ChunkEmbedding, DocumentChunk
from app.rag.chunking import chunk_text
from app.rag.config import ChunkConfig
from app.services.indexing import index_document, prepare_index


class IndexingTests(RagDatabaseMixin, unittest.TestCase):
    def index(self, **overrides):
        return index_document(
            **(
                dict(
                    engine=self.engine,
                    document_version_id=self.version_id,
                    client=self.embedder,
                    embedding=EMBEDDING,
                    chunking=CHUNKING,
                )
                | overrides
            )
        )

    def count(self, model):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(model))

    def test_first_index_then_exact_repeat_without_api(self):
        first, second = self.index(), self.index()
        self.assertEqual((first.chunks_created, first.embeddings_created), (1, 1))
        self.assertEqual((second.chunks_created, second.embeddings_created), (0, 0))
        self.assertEqual((second.chunks_reused, second.embeddings_reused), (1, 1))
        self.assertEqual(len(self.embedder.calls), 1)

    def test_model_and_chunker_changes_append(self):
        self.index()
        changed = self.index(
            embedding=EMBEDDING.model_copy(update={"model": "another-model"})
        )
        self.assertEqual((changed.chunks_reused, changed.embeddings_created), (1, 1))
        changed = self.index(chunker_version="v2")
        self.assertEqual((changed.chunks_created, changed.embeddings_created), (1, 1))
        self.assertEqual(self.count(DocumentChunk), 2)
        self.assertEqual(self.count(ChunkEmbedding), 3)

    def test_same_version_rejects_changed_chunk_config_even_for_short_document(self):
        self.index()
        with self.assertRaises(ValueError):
            self.index(chunking=ChunkConfig(size=1000, overlap=100))
        self.assertEqual(self.count(DocumentChunk), 1)

    def test_ineligible_and_prepare_only_do_not_write_or_embed(self):
        for status, text in (
            ("empty", None),
            ("failed", "source"),
            ("extracted", "  "),
        ):
            version_id = self.add_version(text, status)
            self.assertTrue(self.index(document_version_id=version_id).skipped)
        self.assertTrue(prepare_index(self.engine, self.version_id, CHUNKING))
        self.assertEqual(self.count(DocumentChunk), 0)
        self.assertEqual(self.embedder.calls, [])

    def test_bad_vectors_and_provider_error_do_not_persist_embeddings(self):
        for vectors in (
            [],
            [[1.0]],
            [vector(float("nan"))],
            [vector(float("inf"))],
            [vector(1e100)],
            [vector(True)],
            [vector(0, 0)],
            [vector(), vector()],
        ):
            with (
                self.subTest(vectors=str(vectors)[:40]),
                self.assertRaises(ProviderError),
            ):
                self.index(client=FakeEmbeddingClient(vectors=vectors))
            self.assertEqual(self.count(ChunkEmbedding), 0)
        with self.assertRaises(ProviderError) as error:
            self.index(client=FakeEmbeddingClient(error=RuntimeError("secret headers")))
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(self.count(ChunkEmbedding), 0)
        self.assertEqual(self.index().embeddings_created, 1)

    def test_batch_order_and_transaction_boundaries(self):
        text = "\n\n".join(f"Paragraph {i}. " + "source " * 60 for i in range(12))
        version_id = self.add_version(text)
        config = ChunkConfig(size=512, overlap=100)
        expected = chunk_text(text, config)
        self.index(
            document_version_id=version_id,
            chunking=config,
            embedding=EMBEDDING.model_copy(update={"batch_size": 2}),
        )
        self.assertTrue(all(len(call[0]) <= 2 for call in self.embedder.calls))
        self.assertEqual(
            [text for call in self.embedder.calls for text in call[0]],
            [chunk.text for chunk in expected],
        )

    def test_recheck_reuses_embedding_inserted_during_api_call(self):
        called = False

        def competing_writer():
            nonlocal called
            if not called:
                called = True
                self.index(client=FakeEmbeddingClient())

        result = self.index(client=FakeEmbeddingClient(before_call=competing_writer))
        self.assertEqual(result.embeddings_created, 0)
        self.assertEqual(result.embeddings_reused, 1)

    def test_partial_batch_failure_resumes_only_missing_embeddings(self):
        version_id = self.add_version("paragraph words " * 400)
        embedding = EMBEDDING.model_copy(update={"batch_size": 1})

        def fail_second_batch():
            if len(self.embedder.calls) == 1:
                raise RuntimeError("Synthetic failure")

        self.embedder.before_call = fail_second_batch
        with self.assertRaises(ProviderError):
            self.index(document_version_id=version_id, embedding=embedding)
        self.assertEqual(self.count(ChunkEmbedding), 1)
        self.embedder.before_call = lambda: self.assertEqual(self.transactions, 0)
        result = self.index(document_version_id=version_id, embedding=embedding)
        self.assertEqual(result.embeddings_reused, 1)
        self.assertEqual(result.chunks_created, 0)
        self.assertEqual(self.count(ChunkEmbedding), self.count(DocumentChunk))
