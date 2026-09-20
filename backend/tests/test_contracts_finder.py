import copy
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from app.scrapers.contracts_finder import (
    BATCH_LIMIT,
    SEARCH_URL,
    fetch_releases,
    parse_releases,
)
from app.scrapers.errors import SourceFetchError, SourceParseError

FIXTURE = Path(__file__).parent / "fixtures" / "contracts_finder.json"


class ContractsFinderParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        blocker = patch.object(
            httpx.Client,
            "send",
            side_effect=AssertionError("No live HTTP in parser tests"),
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def test_real_api_fields(self) -> None:
        listing = parse_releases(self.payload)
        self.assertEqual(
            (listing.discovered, listing.failed, listing.skipped), (2, 0, 0)
        )
        tender = listing.records[0]
        self.assertEqual(tender.external_id, "76371b58-f056-4c76-80d6-f175126a0eaf")
        self.assertEqual(tender.title, "Procurement of office and IT equipment")
        self.assertEqual(tender.organization, "Chemonics International, Inc.")
        self.assertEqual(
            str(tender.source_url),
            "https://www.contractsfinder.service.gov.uk/Notice/76371b58-f056-4c76-80d6-f175126a0eaf",
        )
        self.assertEqual(tender.category, "goods")
        self.assertEqual(tender.location, "Ukraine")
        self.assertEqual(
            tender.published_at, datetime(2026, 9, 19, 2, 40, 43, tzinfo=UTC)
        )
        self.assertEqual(tender.deadline, datetime(2026, 10, 3, 9, tzinfo=UTC))
        self.assertNotIn("\n", tender.description)

    def test_notice_identity_does_not_use_release_version_or_buyer_reference(
        self,
    ) -> None:
        before = parse_releases(self.payload).records[0]
        release = self.payload["releases"][0]
        release["id"] = "different-release-version"
        release["tender"]["id"] = "different-buyer-reference"
        after = parse_releases(self.payload).records[0]
        self.assertEqual(before.external_id, after.external_id)
        self.assertNotEqual(after.external_id, release["ocid"])

    def test_optional_fields_missing_and_empty_arrays(self) -> None:
        release = self.payload["releases"][0]
        release.pop("buyer")
        release["parties"] = []
        tender = release["tender"]
        for name in (
            "description",
            "mainProcurementCategory",
            "datePublished",
            "tenderPeriod",
        ):
            tender.pop(name, None)
        tender["items"] = []
        record = parse_releases(self.payload).records[0]
        for name in (
            "organization",
            "description",
            "category",
            "location",
            "published_at",
            "deadline",
        ):
            self.assertIsNone(getattr(record, name))
        self.assertIsNotNone(release["date"])

    def test_normalizes_whitespace_and_multiple_buyers_and_countries(self) -> None:
        release = self.payload["releases"][0]
        release["buyer"] = None
        release["parties"] = [
            {"name": " Beta\n Council ", "roles": ["buyer"]},
            {"name": "Alpha Council", "roles": ["buyer"]},
            {"name": "Supplier", "roles": ["supplier"]},
        ]
        release["tender"]["title"] = "  Office\t equipment\n supply "
        release["tender"]["items"] = [
            {
                "deliveryAddresses": [
                    {"countryName": "Ukraine"},
                    {"countryName": " Poland "},
                    {"countryName": "Ukraine"},
                ]
            }
        ]
        record = parse_releases(self.payload).records[0]
        self.assertEqual(record.title, "Office equipment supply")
        self.assertEqual(record.organization, "Alpha Council; Beta Council")
        self.assertEqual(record.location, "Poland; Ukraine")

    def test_buyer_reference_resolves_without_including_other_parties(self) -> None:
        release = self.payload["releases"][0]
        release["buyer"].pop("name")
        release["parties"].append(
            {"id": "other", "name": "Other Buyer", "roles": ["buyer"]}
        )
        self.assertEqual(
            parse_releases(self.payload).records[0].organization,
            "Chemonics International, Inc.",
        )

    def test_malformed_records_are_isolated(self) -> None:
        for field, value in (
            ("title", "  "),
            ("tenderPeriod", []),
            ("tenderPeriod", {"endDate": "2026-10-01T12:00:00"}),
            ("datePublished", "not a date"),
            ("items", ["broken"]),
            ("documents", []),
            ("status", None),
        ):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(self.payload)
                payload["releases"][0]["tender"][field] = value
                with self.assertLogs("app.scrapers.contracts_finder", level="WARNING"):
                    listing = parse_releases(payload)
                self.assertEqual(
                    (listing.discovered, listing.failed, len(listing.records)),
                    (2, 1, 1),
                )
        self.payload["releases"][0] = 123
        with self.assertLogs("app.scrapers.contracts_finder", level="WARNING"):
            self.assertEqual(parse_releases(self.payload).failed, 1)

    def test_notice_url_cannot_be_attachment_external_or_ambiguous(self) -> None:
        original = self.payload["releases"][0]["tender"]["documents"][0]
        for url in (
            "https://example.org/notice",
            "https://www.contractsfinder.service.gov.uk/Notice/Attachment/file",
            "https://[invalid",
        ):
            payload = copy.deepcopy(self.payload)
            payload["releases"][0]["tender"]["documents"][0]["url"] = url
            with (
                self.subTest(url=url),
                self.assertLogs("app.scrapers.contracts_finder", level="WARNING"),
            ):
                self.assertEqual(parse_releases(payload).failed, 1)
        self.payload["releases"][0]["tender"]["documents"].append(
            original
            | {
                "url": "https://www.contractsfinder.service.gov.uk/Notice/6f10df35-baaa-4e86-9ced-05185c786d82"
            }
        )
        with self.assertLogs("app.scrapers.contracts_finder", level="WARNING"):
            self.assertEqual(parse_releases(self.payload).failed, 1)

    def test_source_structure_and_all_invalid_fail_but_empty_is_valid(self) -> None:
        for payload in (None, [], {}, {"releases": {}}, {"error": "unavailable"}):
            with self.subTest(payload=payload), self.assertRaises(SourceParseError):
                parse_releases(payload)
        with (
            self.assertLogs("app.scrapers.contracts_finder", level="WARNING"),
            self.assertRaises(SourceParseError),
        ):
            parse_releases({"releases": [None, {}]})
        self.assertEqual(parse_releases({"releases": []}).discovered, 0)

    def test_other_stages_and_inactive_tenders_are_skipped(self) -> None:
        self.payload["releases"][0]["tag"] = ["award"]
        self.payload["releases"][1]["tender"]["status"] = "complete"
        listing = parse_releases(self.payload)
        self.assertEqual(
            (listing.discovered, listing.skipped, listing.failed), (2, 2, 0)
        )


class ContractsFinderFetchTests(unittest.TestCase):
    def test_one_bounded_request_without_auth_or_detail_calls(self) -> None:
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(str(request.url).split("?")[0], SEARCH_URL)
            self.assertEqual(request.url.params["stages"], "tender")
            self.assertEqual(request.url.params["limit"], str(BATCH_LIMIT))
            self.assertEqual(request.extensions["timeout"]["read"], 30.0)
            self.assertTrue(request.headers["user-agent"].startswith("TenderScoutAI/"))
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(
                200,
                json={"releases": [], "links": {"next": "https://example.org/next"}},
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(fetch_releases(client)["releases"], [])
        self.assertEqual(len(requests), 1)

    def test_http_errors_and_timeouts_stop_without_retry(self) -> None:
        for status in (403, 429, 500, 302, "timeout"):
            requests = []

            def respond(request):
                requests.append(request)
                if status == "timeout":
                    raise httpx.ReadTimeout("Timeout", request=request)
                return httpx.Response(
                    status, headers={"location": "https://example.org/login"}
                )

            with (
                self.subTest(status=status),
                httpx.Client(
                    transport=httpx.MockTransport(respond), follow_redirects=True
                ) as client,
                self.assertLogs("app.scrapers.contracts_finder", level="ERROR"),
                self.assertRaises(SourceFetchError),
            ):
                fetch_releases(client)
            self.assertEqual(len(requests), 1)

    def test_wrong_content_type_and_invalid_json(self) -> None:
        for media_type, body, error in (
            ("text/html", "<html>Unavailable</html>", SourceFetchError),
            ("application/json", "not json", SourceParseError),
        ):
            with (
                self.subTest(media_type=media_type),
                httpx.Client(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(
                            200, headers={"content-type": media_type}, text=body
                        )
                    )
                ) as client,
                self.assertRaises(error),
            ):
                fetch_releases(client)
