import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.scrapers.contracts_finder import notice_identity
from app.scrapers.contracts_finder_documents import discover_documents
from app.scrapers.errors import SourceParseError
from app.scrapers.records import DiscoveredDocument
from app.services.document_download import supported_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "contracts_finder_documents.json"


class DocumentDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.tender = self.payload["releases"][0]["tender"]
        blocker = patch(
            "httpx.Client.send", side_effect=AssertionError("Parser attempted HTTP")
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def test_real_fixture_uses_notice_identity_and_skips_html_notice(self) -> None:
        listing = discover_documents(self.payload)
        self.assertEqual(listing.failed, 0)
        self.assertEqual(len(listing.records), 3)
        pdf = next(record for record in listing.records if supported_pdf(record))
        self.assertEqual(pdf.tender_external_id, notice_identity(self.tender)[0])
        self.assertEqual(pdf.source_document_id, "3")
        self.assertEqual(pdf.document_type, "tenderNotice")
        self.assertEqual(pdf.media_type, "application/pdf")
        self.assertIsNone(pdf.title)
        self.assertNotIn(
            notice_identity(self.tender)[1],
            [str(r.source_url) for r in listing.records],
        )

    def test_optional_title_and_external_metadata_are_preserved(self) -> None:
        # Synthetic variation: the captured public attachment has no title.
        self.tender["documents"][2]["title"] = "  Procurement specification  "
        self.tender["documents"].append(
            {
                "id": "external",
                "url": "https://supplier.example/spec.pdf",
                "format": "application/pdf",
            }
        )
        listing = discover_documents(self.payload)
        self.assertEqual(listing.records[1].title, "Procurement specification")
        self.assertEqual(listing.records[-1].source_document_id, "external")
        self.assertFalse(supported_pdf(listing.records[-1]))

    def test_bad_attachment_does_not_discard_valid_siblings(self) -> None:
        self.tender["documents"].append({"url": "file:///private/document.pdf"})
        listing = discover_documents(self.payload)
        self.assertEqual(listing.failed, 1)
        self.assertEqual(len(listing.records), 3)

    def test_missing_parent_identity_is_not_replaced_by_ocid(self) -> None:
        self.tender["documents"].pop(0)
        listing = discover_documents(self.payload)
        self.assertEqual(listing.failed, 1)
        self.assertEqual(listing.records, [])

    def test_invalid_package_and_empty_batch(self) -> None:
        for value in ([], {}, {"releases": {}}):
            with self.subTest(value=value), self.assertRaises(SourceParseError):
                discover_documents(value)
        self.assertEqual(discover_documents({"releases": []}).records, [])

    def test_contract_rejects_internal_fields_and_non_http_urls(self) -> None:
        base = {"tender_external_id": "notice", "source_url": "https://example.com/doc"}
        for extra in (
            {"content_hash": "a" * 64},
            {"source_url": "ftp://example.com/doc"},
            {"tender_external_id": ""},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                DiscoveredDocument(**(base | extra))
