import unittest
from datetime import UTC, datetime

import httpx

from app.scrapers import world_bank
from app.scrapers.errors import SourceFetchError, SourceParseError


class WorldBankTests(unittest.TestCase):
    def test_parse_notice_normalizes_valid_record(self):
        notice = {
            "id": "OP12345678",
            "notice_type": "Invitation for Bids",
            "notice_status": "Published",
            "noticedate": "2026-09-25T00:00:00Z",
            "submission_deadline_date": "31-Oct-2026",
            "project_ctry_name": "Pakistan",
            "project_name": "Digital Services Project",
            "bid_description": "Software development services",
            "procurement_group": "Information Technology",
            "contact_organization": "Example Agency",
        }

        tender = world_bank.parse_notice(notice)

        self.assertEqual(tender.external_id, "OP12345678")
        self.assertEqual(tender.title, "Software development services")
        self.assertEqual(tender.description, "Software development services")
        self.assertEqual(tender.organization, "Example Agency")
        self.assertEqual(tender.category, "Information Technology")
        self.assertEqual(tender.location, "Pakistan")
        self.assertEqual(
            tender.published_at,
            datetime(2026, 9, 25, tzinfo=UTC),
        )
        self.assertEqual(
            tender.deadline,
            datetime(2026, 10, 31, tzinfo=UTC),
        )
        self.assertEqual(
            str(tender.source_url),
            "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP12345678",
        )

    def test_fetch_uses_bounded_query_and_returns_records(self):
        payload = {
            "procnotices": [
                {
                    "id": "OP12345678",
                    "notice_type": "Invitation for Bids",
                    "notice_status": "Published",
                    "noticedate": "2026-09-25T00:00:00Z",
                    "submission_deadline_date": "31-Oct-2026",
                    "project_ctry_name": "Pakistan",
                    "project_name": "Digital Services Project",
                    "bid_description": "Software development services",
                    "procurement_group": "Information Technology",
                    "contact_organization": "Example Agency",
                }
            ]
        }

        def handler(request):
            self.assertEqual(request.url.host, "search.worldbank.org")
            self.assertEqual(request.url.path, "/api/v2/procnotices")
            self.assertEqual(request.url.params["rows"], "5")
            self.assertEqual(request.url.params["os"], "0")
            self.assertEqual(request.url.params["qterm"], "software")
            self.assertEqual(request.url.params["order"], "desc")

            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=payload,
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            listing = world_bank.fetch(
                client,
                limit=5,
                timeout=4.0,
                query="software",
            )

        self.assertEqual(len(listing.records), 1)
        self.assertEqual(listing.skipped, 0)
        self.assertEqual(
            listing.records[0].external_id,
            "OP12345678",
        )

    def test_invalid_records_are_skipped(self):
        payload = {
            "procnotices": [
                {"id": "invalid"},
                {
                    "id": "OP12345678",
                    "notice_type": "Invitation for Bids",
                    "notice_status": "Published",
                    "noticedate": "2026-09-25T00:00:00Z",
                    "submission_deadline_date": "31-Oct-2026",
                    "project_ctry_name": "Pakistan",
                    "project_name": "Digital Services Project",
                    "bid_description": "Software development services",
                    "procurement_group": "Information Technology",
                    "contact_organization": "Example Agency",
                },
            ]
        }

        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json=payload,
                )
            )
        ) as client:
            listing = world_bank.fetch(
                client,
                limit=10,
                timeout=2.0,
            )

        self.assertEqual(len(listing.records), 1)
        self.assertEqual(listing.skipped, 1)

    def test_http_error_is_sanitized(self):
        with (
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        503,
                        json={"private": "secret-response-body"},
                    )
                )
            ) as client,
            self.assertRaises(SourceFetchError) as error,
        ):
            world_bank.fetch(
                client,
                limit=2,
                timeout=1.0,
            )

        self.assertNotIn(
            "secret-response-body",
            str(error.exception),
        )

    def test_invalid_media_type_fails(self):
        with (
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        headers={"content-type": "text/html"},
                        text="private-response-body",
                    )
                )
            ) as client,
            self.assertRaises(SourceFetchError),
        ):
            world_bank.fetch(
                client,
                limit=2,
                timeout=1.0,
            )

    def test_invalid_json_shape_fails(self):
        for payload in ({}, {"procnotices": {}}, {"procnotices": None}):
            with (
                httpx.Client(
                    transport=httpx.MockTransport(
                        lambda request, payload=payload: httpx.Response(
                            200,
                            headers={"content-type": "application/json"},
                            json=payload,
                        )
                    )
                ) as client,
                self.assertRaises(SourceParseError),
            ):
                world_bank.fetch(
                    client,
                    limit=2,
                    timeout=1.0,
                )

    def test_limit_validation(self):
        with httpx.Client() as client:
            with self.assertRaises(ValueError):
                world_bank.fetch(
                    client,
                    limit=0,
                    timeout=1.0,
                )

            with self.assertRaises(ValueError):
                world_bank.fetch(
                    client,
                    limit=101,
                    timeout=1.0,
                )


if __name__ == "__main__":
    unittest.main()
