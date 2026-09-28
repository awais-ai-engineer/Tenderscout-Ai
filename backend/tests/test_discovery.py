import unittest
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import app
from app.models import Base, Tender, TenderRevision
from app.scrapers.records import ParsedListing, ScrapedTender
from app.services import discovery, ingestion
from app.sources import connector

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def record(source, external_id, title, *, description=None, organization=None):
    host = {
        "contracts-finder": "www.contractsfinder.service.gov.uk",
        "find-a-tender": "www.find-tender.service.gov.uk",
        "ted": "ted.europa.eu",
        "world-bank": "projects.worldbank.org",
    }[source]
    return ScrapedTender(
        external_id=external_id,
        source_url=f"https://{host}/Notice/{external_id}",
        title=title,
        description=description,
        organization=organization,
    )


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.contracts = record(
            "contracts-finder",
            "contract-1",
            "Cloud hosting services",
            organization="City Council",
        )
        self.find = record(
            "find-a-tender",
            "find-1",
            "IT services",
            description="Cloud hosting required",
        )
        self.ted = record(
            "ted", "123456-2026", "Cloud infrastructure", organization="EU Agency"
        )
        self.world_bank = record(
            "world-bank",
            "OP12345678",
            "Software development services",
            description="Cloud migration support",
            organization="World Bank Example Agency",
        )
        self.calls = []

    def fetch(self, slug, query):
        self.calls.append(slug)
        item = {
            "contracts-finder": self.contracts,
            "find-a-tender": self.find,
            "ted": self.ted,
            "world-bank": self.world_bank,
        }[slug]
        return ParsedListing([item, item]), NOW

    def search(self, **kwargs):
        with patch.object(discovery, "search_source", side_effect=self.fetch):
            return discovery.search(self.engine, q="cloud", **kwargs)

    def test_query_validation_and_bounds(self):
        self.assertEqual(
            discovery.normalize_query("  cloud   hosting  "), "cloud hosting"
        )
        self.assertEqual(discovery.normalize_query("   "), "")
        for value in ("ab", "x" * 256):
            with self.assertRaises(discovery.InvalidQuery):
                discovery.normalize_query(value)
        with self.assertRaises(discovery.InvalidQuery):
            self.search(cursor=1)
        self.assertEqual(self.calls, [])

    def test_all_sources_fresh_and_ranked(self):
        result = self.search(limit=1)
        self.assertCountEqual(
            self.calls,
            ["contracts-finder", "find-a-tender", "ted", "world-bank"],
        )
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["items"][0]["title"], "Cloud infrastructure")
        self.assertTrue(result["items"][0]["freshly_fetched"])
        self.assertEqual(
            [s["status"] for s in result["sources"]],
            ["success", "success", "success", "success"],
        )
        self.assertEqual(
            [s["fetched_at"] for s in result["sources"]],
            [NOW, NOW, NOW, NOW],
        )
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Tender.id))), 4)
        self.assertEqual(self.search()["result_count"], 4)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Tender.id))), 4)

    def test_source_selection_and_persisted_update(self):
        first = self.search(source="contracts-finder")
        self.assertEqual(self.calls, ["contracts-finder"])
        self.assertEqual(len(first["sources"]), 1)
        self.contracts = self.contracts.model_copy(
            update={"title": "Cloud hosting renewal"}
        )
        second = self.search(source="contracts-finder")
        self.assertEqual(second["items"][0]["title"], "Cloud hosting renewal")
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Tender.id))), 1)
            self.assertEqual(session.scalar(select(func.count(TenderRevision.id))), 2)

    def test_ted_source_filter_calls_only_ted(self):
        result = self.search(source="ted")
        self.assertEqual(self.calls, ["ted"])
        self.assertEqual(result["sources"][0]["source"], "ted")
        self.assertEqual(result["items"][0]["source"], "ted")

    def test_one_failure_uses_recorded_fallback_without_fresh_label(self):
        ingestion.ingest_tenders(
            self.engine, connector("find-a-tender").source, ParsedListing([self.find])
        )

        def partial(slug, query):
            if slug == "find-a-tender":
                raise RuntimeError("private upstream detail")
            return self.fetch(slug, query)

        with patch.object(discovery, "search_source", side_effect=partial):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(
            [s["status"] for s in result["sources"]],
            ["success", "unavailable", "success", "success"],
        )
        self.assertEqual(result["sources"][1]["error_code"], "source_unavailable")
        self.assertNotIn("private upstream detail", str(result))
        self.assertEqual(
            {row["source"]: row["freshly_fetched"] for row in result["items"]},
            {
                "contracts-finder": True,
                "find-a-tender": False,
                "ted": True,
                "world-bank": True,
            },
        )

    def test_both_failures_return_recorded_results(self):
        ingestion.ingest_tenders(
            self.engine,
            connector("contracts-finder").source,
            ParsedListing([self.contracts]),
        )
        with patch.object(
            discovery, "search_source", side_effect=RuntimeError("upstream")
        ):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(result["result_count"], 1)
        self.assertFalse(result["items"][0]["freshly_fetched"])
        self.assertEqual(
            [s["status"] for s in result["sources"]],
            ["unavailable", "unavailable", "unavailable", "unavailable"],
        )

    def test_two_failures_keep_third_source_useful(self):
        def partial(slug, query):
            if slug != "ted":
                raise RuntimeError("private upstream detail")
            return self.fetch(slug, query)

        with patch.object(discovery, "search_source", side_effect=partial):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["items"][0]["source"], "ted")
        self.assertEqual(
            [item["status"] for item in result["sources"]],
            ["unavailable", "unavailable", "success", "unavailable"],
        )

    def test_empty_query_does_not_fetch(self):
        with patch.object(
            discovery, "search_source", side_effect=AssertionError("must not fetch")
        ):
            result = discovery.search(self.engine, q=" ")
        self.assertEqual(result["mode"], "recorded")
        self.assertEqual(result["sources"], [])

    def test_source_fetches_overlap(self):
        barrier = Barrier(4, timeout=2)

        def concurrent(slug, query):
            barrier.wait()
            return self.fetch(slug, query)

        with patch.object(discovery, "search_source", side_effect=concurrent):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(len(result["sources"]), 4)
        self.assertTrue(all(item["status"] == "success" for item in result["sources"]))

    def test_api_contract_and_sanitized_errors(self):
        settings = Settings(_env_file=None, postgres_password="test-only")
        with (
            patch("app.main.create_database_engine", return_value=self.engine),
            patch("app.main.Settings", return_value=settings),
            patch.object(discovery, "search_source", side_effect=self.fetch),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            base = "/api/v1/discover"
            self.assertEqual(client.get(base).json()["mode"], "recorded")
            self.assertEqual(self.calls, [])
            invalid = client.get(base, params={"q": "ab"})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["error"]["code"], "invalid_query")
            invalid_limit = client.get(base, params={"q": "cloud", "limit": 101})
            self.assertEqual(invalid_limit.status_code, 422)
            self.assertEqual(self.calls, [])
            filtered = client.get(
                base, params={"q": "cloud", "source": "find-a-tender"}
            )
            self.assertEqual(filtered.status_code, 200, filtered.text)
            self.assertEqual(self.calls, ["find-a-tender"])
            self.assertEqual(filtered.json()["sources"][0]["source"], "find-a-tender")
            self.assertTrue(filtered.json()["requested_at"].endswith("Z"))

    def test_api_partial_failure_is_200(self):
        settings = Settings(_env_file=None, postgres_password="test-only")

        def partial(slug, query):
            if slug == "find-a-tender":
                raise RuntimeError("private upstream detail")
            return self.fetch(slug, query)

        with (
            patch("app.main.create_database_engine", return_value=self.engine),
            patch("app.main.Settings", return_value=settings),
            patch.object(discovery, "search_source", side_effect=partial),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            response = client.get("/api/v1/discover?q=cloud")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["sources"][1]["status"], "unavailable")
            self.assertNotIn("private upstream detail", response.text)

    def test_api_no_source_and_no_recorded_fallback_has_stable_error(self):
        settings = Settings(_env_file=None, postgres_password="test-only")
        with (
            patch("app.main.create_database_engine", return_value=self.engine),
            patch("app.main.Settings", return_value=settings),
            patch.object(
                discovery,
                "search_source",
                side_effect=RuntimeError("private upstream detail"),
            ),
            patch.object(
                discovery.queries,
                "discover_tenders",
                side_effect=SQLAlchemyError("private database detail"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            response = client.get("/api/v1/discover?q=cloud")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["error"]["code"], "live_search_unavailable"
            )
            self.assertNotIn("private", response.text)


if __name__ == "__main__":
    unittest.main()
