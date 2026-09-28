import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from app.scrapers import ted
from app.scrapers.errors import SourceFetchError, SourceParseError

FIXTURE = Path(__file__).parent / "fixtures" / "ted_search.json"


class TedTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_normalizes_documented_search_fields(self):
        listing = ted.parse_notices(self.payload)
        self.assertEqual((listing.discovered, listing.failed), (2, 0))
        first = listing.records[0]
        self.assertEqual(first.external_id, "123456-2026")
        self.assertEqual(first.title, "Cloud infrastructure services")
        self.assertEqual(first.organization, "European Example Agency")
        self.assertEqual(first.category, "72500000")
        self.assertEqual(first.location, "BEL")
        self.assertEqual(first.published_at, datetime(2026, 9, 25, tzinfo=UTC))
        self.assertEqual(first.deadline, datetime(2026, 10, 31, tzinfo=UTC))
        self.assertEqual(
            str(first.source_url),
            "https://ted.europa.eu/en/notice/-/detail/123456-2026",
        )
        self.assertEqual(listing.records[1].title, "Services de conseil")
        self.assertIsNone(listing.records[1].description)

    def test_malformed_records_are_isolated_and_all_invalid_fails(self):
        self.payload["notices"].insert(0, {"publication-number": "invalid"})
        with self.assertLogs("app.scrapers.ted", level="WARNING"):
            listing = ted.parse_notices(self.payload)
        self.assertEqual((len(listing.records), listing.failed), (2, 1))
        with self.assertRaises(SourceParseError):
            ted.parse_notices(
                {"notices": [{"publication-number": "invalid"}], "timedOut": False}
            )
        for payload in ({}, {"notices": {}, "timedOut": False}):
            with self.assertRaises(SourceParseError):
                ted.parse_notices(payload)
        with self.assertRaises(SourceFetchError):
            ted.parse_notices({"notices": [], "timedOut": True})

    def test_official_search_request_is_bounded_and_query_escaped(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(request.url, httpx.URL(ted.SEARCH_URL))
            self.assertEqual(body["limit"], 7)
            self.assertEqual(body["page"], 1)
            self.assertEqual(body["paginationMode"], "PAGE_NUMBER")
            self.assertEqual(body["scope"], "ACTIVE")
            self.assertEqual(
                body["query"], 'FT~"cloud \\"secure\\"" SORT BY publication-date DESC'
            )
            self.assertEqual(request.extensions["timeout"]["read"], 4.0)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=self.payload,
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            listing = ted.search(client, query='cloud "secure"', limit=7, timeout=4.0)
        self.assertEqual(len(listing.records), 2)

    def test_http_timeout_and_invalid_media_are_sanitized(self):
        for response in (
            httpx.Response(503, json={"private": "body"}),
            httpx.Response(200, headers={"content-type": "text/html"}, text="private"),
        ):
            with (
                httpx.Client(
                    transport=httpx.MockTransport(lambda request: response)
                ) as client,
                self.assertRaises(SourceFetchError) as error,
            ):
                ted.fetch_notices(client, query="FT~cloud", limit=2, timeout=1)
            self.assertNotIn("private", str(error.exception))
        with (
            patch.object(
                httpx.Client,
                "post",
                side_effect=httpx.ReadTimeout("private timeout"),
            ),
            httpx.Client() as client,
            self.assertRaises(SourceFetchError) as error,
        ):
            ted.fetch_notices(client, query="FT~cloud", limit=2, timeout=1)
        self.assertNotIn("private", str(error.exception))


if __name__ == "__main__":
    unittest.main()
