import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from pypdf import PdfWriter

from app.services.pdf_text import extract_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_text.pdf"


class PdfTextTests(unittest.TestCase):
    def test_known_text_and_page_separator(self) -> None:
        result = extract_pdf(FIXTURE, 2)
        self.assertEqual(result.status, "extracted")
        self.assertEqual(
            result.text, "TenderScout fixture page one\n\nTenderScout fixture page two"
        )
        self.assertIsNone(result.error)

    def test_page_limit_fails_before_text_extraction(self) -> None:
        result = extract_pdf(FIXTURE, 1)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "PDF exceeds page limit")
        self.assertIsNone(result.text)

    def test_valid_textless_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(path)
            result = extract_pdf(path, 5)
        self.assertEqual(result.status, "empty")
        self.assertIsNone(result.text)
        self.assertIsNone(result.error)

    def test_malformed_pdf_failure_is_concise(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"%PDF-1.4\nsensitive source content\n%%EOF")
            result = extract_pdf(path, 5)
        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.text)
        self.assertNotIn("sensitive", result.error)
        self.assertLess(len(result.error), 100)

    def test_encrypted_pdf_is_not_decrypted(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "encrypted.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.encrypt("test-only-password")
            writer.write(path)
            result = extract_pdf(path, 5)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "Encrypted PDFs are unsupported")

    def test_parser_errors_outside_pypdf_hierarchy_are_sanitized(self) -> None:
        with patch(
            "app.services.pdf_text.PdfReader",
            side_effect=NotImplementedError("private PDF content"),
        ):
            result = extract_pdf(FIXTURE, 5)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "PDF extraction failed (NotImplementedError)")

    def test_process_interrupt_is_not_swallowed(self) -> None:
        with (
            patch("app.services.pdf_text.PdfReader", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            extract_pdf(FIXTURE, 5)

    def test_nul_cleanup_preserves_paragraphs(self) -> None:
        with patch("app.services.pdf_text.PdfReader") as reader:
            reader.return_value.is_encrypted = False
            page = Mock()
            page.extract_text.return_value = (
                " First\x00 line\nSecond line\n\nParagraph "
            )
            reader.return_value.pages = [page]
            result = extract_pdf(FIXTURE, 5)
        self.assertEqual(result.text, "First line\nSecond line\n\nParagraph")
