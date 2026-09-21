import unittest

from pydantic import ValidationError

from app.core.config import Settings
from app.rag.chunking import chunk_text, normalize_source, text_hash
from app.rag.config import ChunkConfig, EmbeddingConfig
from app.services.retrieval import normalize_question


class ChunkingTests(unittest.TestCase):
    def test_short_empty_and_normalized_source(self):
        text = "  First\r\nline\x00.\r\n\r\nSecond paragraph.  "
        chunks = chunk_text(text, ChunkConfig())
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "First\nline.\n\nSecond paragraph.")
        self.assertEqual(chunks[0].content_hash, text_hash(chunks[0].text))
        self.assertEqual(chunk_text(" \x00\r\n", ChunkConfig()), [])

    def test_long_text_full_fidelity_order_overlap_and_bounds(self):
        text = "\n\n".join(f"Paragraph {i}: " + "words " * 70 for i in range(20))
        config = ChunkConfig(size=512, overlap=100)
        chunks = chunk_text(text, config)
        self.assertEqual(chunks, chunk_text(text, config))
        self.assertGreater(len(chunks), 2)
        covered = set()
        for index, chunk in enumerate(chunks):
            self.assertEqual(chunk.chunk_index, index)
            self.assertEqual(
                chunk.text, normalize_source(text)[chunk.start_char : chunk.end_char]
            )
            self.assertTrue(0 < len(chunk.text) <= 512)
            self.assertEqual(chunk.content_hash, text_hash(chunk.text))
            covered.update(range(chunk.start_char, chunk.end_char))
            if index:
                self.assertGreater(chunk.start_char, chunks[index - 1].start_char)
                self.assertLess(chunk.start_char, chunks[index - 1].end_char)
                self.assertLess(
                    chunks[index - 1].end_char - chunk.start_char, len(chunk.text)
                )
        self.assertEqual(covered, set(range(len(normalize_source(text)))))
        self.assertEqual(chunks[-1].end_char, len(normalize_source(text)))

    def test_long_token_and_zero_overlap_progress(self):
        for overlap in (0, 250, 255):
            chunks = chunk_text("x" * 3000, ChunkConfig(size=256, overlap=overlap))
            self.assertTrue(all(0 < len(chunk.text) <= 256 for chunk in chunks))
            self.assertEqual(chunks[-1].end_char, 3000)

    def test_changed_source_changes_hash(self):
        self.assertNotEqual(
            chunk_text("source A", ChunkConfig())[0].content_hash,
            chunk_text("source B", ChunkConfig())[0].content_hash,
        )

    def test_config_validation(self):
        for values in ({"size": 255}, {"overlap": -1}, {"size": 256, "overlap": 256}):
            with self.assertRaises(ValidationError):
                ChunkConfig(**values)
        for values in ({"dimensions": 3}, {"batch_size": 0}, {"batch_size": 65}):
            with self.assertRaises(ValidationError):
                EmbeddingConfig(model="test", **values)
        for values in (
            {"rag_top_k": 0},
            {"rag_top_k": 21},
            {"rag_max_context_chars": 100},
            {"rag_chunk_size_chars": 256, "rag_chunk_overlap_chars": 256},
            {"ai_embedding_dimensions": 3},
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, postgres_password="test", **values)

    def test_question_normalization_preserves_case_and_internal_whitespace(self):
        self.assertEqual(
            normalize_question(" \r\nWhat  is\rthe Deadline? \n"),
            "What  is\nthe Deadline?",
        )
        for text in (" ", "x\x00y", "x" * 2001):
            with self.assertRaises(ValueError):
                normalize_question(text)
