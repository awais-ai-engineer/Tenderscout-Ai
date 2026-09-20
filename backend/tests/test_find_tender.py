import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.scrapers.find_tender import (
    LISTING_URL,
    USER_AGENT,
    InvalidRecord,
    SourceFetchError,
    SourceParseError,
    fetch_listing,
    parse_date,
    parse_listing,
)
from app.scrapers.records import ScrapedTender

FIXTURE = Path(__file__).parent / "fixtures" / "find_tender_listing.html"


class FindTenderParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.soup = BeautifulSoup(self.html, "html.parser")
        self.network = patch.object(
            httpx.Client,
            "send",
            side_effect=AssertionError("Parser must not use network"),
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_real_listing_fields_and_supported_notice_types(self) -> None:
        listing = parse_listing(self.html)
        self.assertEqual(
            (listing.discovered, listing.failed, listing.skipped), (3, 0, 1)
        )
        self.assertEqual(len(listing.records), 2)
        tender = listing.records[0]
        self.assertEqual(tender.external_id, "088929-2026")
        self.assertEqual(tender.title, "Customer Due Diligence (CDD) Platform")
        self.assertEqual(tender.organization, "Notting Hill Genesis (NHG).")
        self.assertEqual(
            str(tender.source_url),
            LISTING_URL.split("/Search")[0] + "/Notice/088929-2026",
        )
        self.assertEqual(tender.location, "UKI - London")
        self.assertEqual(tender.published_at, datetime(2026, 9, 19, 9, 55, tzinfo=UTC))
        self.assertEqual(tender.deadline, datetime(2026, 10, 19, 11, tzinfo=UTC))
        self.assertIn("cloud-hosted Customer Due Diligence", tender.description)
        self.assertIsNone(tender.category)

    def test_whitespace_relative_links_and_plural_location(self) -> None:
        row = self.soup.select_one(".search-result")
        link = row.select_one("h2 a")
        link.string = "  Customer\n Due\tDiligence \u00a0 Platform  "
        link["href"] = "/Notice/088929-2026?origin=SearchResults#top"
        row.select_one(".search-result-sub-header").string = " Notting\n Hill  Genesis "
        row.find("strong", string="Contract location").string = "Contract locations"
        parsed = parse_listing(str(self.soup)).records[0]
        self.assertEqual(parsed.title, "Customer Due Diligence Platform")
        self.assertEqual(parsed.organization, "Notting Hill Genesis")
        self.assertEqual(parsed.location, "UKI - London")
        self.assertEqual(
            str(parsed.source_url),
            "https://www.find-tender.service.gov.uk/Notice/088929-2026",
        )

    def test_missing_optional_values(self) -> None:
        row = self.soup.select_one(".search-result")
        row.select_one(".search-result-sub-header").decompose()
        row.find(id="088929-2026-description").decompose()
        for label in ("Submission deadline", "Publication date", "Contract location"):
            row.find("strong", string=label).parent.parent.decompose()
        tender = parse_listing(str(self.soup)).records[0]
        for field in (
            "organization",
            "description",
            "deadline",
            "published_at",
            "location",
        ):
            self.assertIsNone(getattr(tender, field))

    def test_malformed_record_does_not_discard_valid_record(self) -> None:
        for href in (
            "https://example.org/Notice/088929-2026",
            "javascript:alert(1)",
            "https://[invalid",
            "/Notice/not-an-id",
        ):
            with self.subTest(href=href):
                self.soup.select_one(".search-result h2 a")["href"] = href
                with self.assertLogs("app.scrapers.find_tender", level="WARNING"):
                    listing = parse_listing(str(self.soup))
                self.assertEqual((listing.failed, len(listing.records)), (1, 1))
                self.assertEqual(listing.records[0].external_id, "088927-2026")

    def test_invalid_date_or_required_title_is_isolated(self) -> None:
        for selector in ("date", "title", "missing link", "notice type"):
            with self.subTest(selector=selector):
                soup = BeautifulSoup(self.html, "html.parser")
                row = soup.select_one(".search-result")
                if selector == "date":
                    row.find(
                        "strong", string="Submission deadline"
                    ).parent.find_next_sibling("dd").string = "not a date"
                elif selector == "title":
                    row.select_one("h2 a").string = "   "
                elif selector == "missing link":
                    row.select_one("h2 a").decompose()
                else:
                    row.find("strong", string="Notice type").parent.parent.decompose()
                with self.assertLogs("app.scrapers.find_tender", level="WARNING"):
                    listing = parse_listing(str(soup))
                self.assertEqual((listing.failed, len(listing.records)), (1, 1))

    def test_broken_structure_is_not_an_empty_listing(self) -> None:
        for html in (
            "<html>Service temporarily unavailable</html>",
            '<span class="search-result-count">3</span>'
            '<div id="dashboard_notices"></div>',
            '<span class="search-result-count">,</span>'
            '<div id="dashboard_notices"></div>',
        ):
            with self.subTest(html=html), self.assertRaises(SourceParseError):
                parse_listing(html)
        for link in self.soup.select(".search-result h2 a"):
            link.decompose()
        with (
            self.assertLogs("app.scrapers.find_tender", level="WARNING"),
            self.assertRaises(SourceParseError),
        ):
            parse_listing(str(self.soup))

    def test_zero_notices_and_no_supported_notices_are_explicit(self) -> None:
        listing = parse_listing(
            '<span class="search-result-count">0</span>'
            '<div id="dashboard_notices"></div>'
        )
        self.assertEqual(listing.discovered, 0)
        listing = parse_listing(
            self.html.replace("UK4: Tender notice", "UK6: Contract award notice")
        )
        self.assertEqual(
            (listing.discovered, listing.skipped, listing.failed), (3, 3, 0)
        )

    def test_dates_handle_uk_dst_noon_and_midnight(self) -> None:
        examples = {
            "19 January 2026, 12:00am": datetime(2026, 1, 19, tzinfo=UTC),
            "19 January 2026, 12:00pm": datetime(2026, 1, 19, 12, tzinfo=UTC),
            "19 July 2026, 12:00pm": datetime(2026, 7, 19, 11, tzinfo=UTC),
        }
        for value, expected in examples.items():
            with self.subTest(value=value):
                self.assertEqual(parse_date(value), expected)
        for invalid in (
            "31 February 2026, 12:00pm",
            "19 July 2026",
            "19 July 2026, 13:00pm",
            "29 March 2026, 1:30am",
            "25 October 2026, 1:30am",
        ):
            with self.subTest(value=invalid), self.assertRaises(InvalidRecord):
                parse_date(invalid)

    def test_internal_contract_rejects_invalid_urls_naive_dates_and_db_fields(
        self,
    ) -> None:
        valid = {"title": "Tender", "source_url": "https://example.org/tender"}
        for invalid in (
            {"source_url": "not-a-url"},
            {"deadline": "2026-10-01T12:00:00"},
            {"source_id": 1},
            {"id": 1},
            {"created_at": "2026-10-01T12:00:00Z"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ScrapedTender.model_validate(valid | invalid)


class FindTenderFetchTests(unittest.TestCase):
    def test_fetch_has_timeout_user_agent_and_no_detail_requests(self) -> None:
        paths = []

        def respond(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            self.assertEqual(request.headers["user-agent"], USER_AGENT)
            self.assertEqual(request.extensions["timeout"]["read"], 20.0)
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(
                200, text="<html>Listing</html>", headers={"content-type": "text/html"}
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(fetch_listing(client), "<html>Listing</html>")
        self.assertEqual(paths, ["/robots.txt", "/Search/Results"])

    def test_http_failures_and_timeout_are_not_retried(self) -> None:
        for failure in (403, 429, 500, "timeout"):
            paths = []

            def respond(request: httpx.Request) -> httpx.Response:
                paths.append(request.url.path)
                if request.url.path == "/robots.txt":
                    return httpx.Response(404)
                if failure == "timeout":
                    raise httpx.ReadTimeout("Timed out", request=request)
                return httpx.Response(failure)

            with (
                self.subTest(failure=failure),
                httpx.Client(transport=httpx.MockTransport(respond)) as client,
                self.assertLogs("app.scrapers.find_tender", level="ERROR"),
                self.assertRaises(SourceFetchError),
            ):
                fetch_listing(client)
            self.assertEqual(paths, ["/robots.txt", "/Search/Results"])

    def test_robots_denial_stops_before_listing(self) -> None:
        paths = []

        def respond(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, text="User-agent: *\nDisallow: /Search/")

        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            self.assertRaises(SourceFetchError),
        ):
            fetch_listing(client)
        self.assertEqual(paths, ["/robots.txt"])

    def test_redirects_and_non_html_responses_fail(self) -> None:
        for status in (302, 200):
            paths = []

            def respond(request: httpx.Request) -> httpx.Response:
                paths.append(request.url.path)
                if request.url.path == "/robots.txt":
                    return httpx.Response(404)
                return httpx.Response(
                    status,
                    headers={
                        "location": "https://example.org/login",
                        "content-type": "application/json",
                    },
                    text="{}",
                )

            with (
                self.subTest(status=status),
                httpx.Client(
                    transport=httpx.MockTransport(respond), follow_redirects=True
                ) as client,
                self.assertRaises(SourceFetchError),
            ):
                fetch_listing(client)
            self.assertEqual(paths, ["/robots.txt", "/Search/Results"])
