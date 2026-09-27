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

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def record(source, external_id, title, *, description=None, organization=None):
    host = (
        "www.contractsfinder.service.gov.uk"
        if source == "contracts-finder"
        else "www.find-tender.service.gov.uk"
    )
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
        self.calls = []

    def fetch(self, slug):
        self.calls.append(slug)
        item = self.contracts if slug == "contracts-finder" else self.find
        return ParsedListing([item, item]), NOW

    def search(self, **kwargs):
        with patch.object(discovery, "fetch_source", side_effect=self.fetch):
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

    def test_both_sources_fresh_deduplicated_and_ranked(self):
        result = self.search(limit=1)
        self.assertCountEqual(self.calls, ["contracts-finder", "find-a-tender"])
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["items"][0]["title"], "Cloud hosting services")
        self.assertTrue(result["items"][0]["freshly_fetched"])
        self.assertEqual(
            [s["status"] for s in result["sources"]], ["success", "success"]
        )
        self.assertEqual([s["fetched_at"] for s in result["sources"]], [NOW, NOW])
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Tender.id))), 2)
        self.assertEqual(self.search()["result_count"], 2)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Tender.id))), 2)

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

    def test_one_failure_uses_recorded_fallback_without_fresh_label(self):
        ingestion.ingest_tenders(
            self.engine, discovery.SOURCES["find-a-tender"], ParsedListing([self.find])
        )

        def partial(slug):
            if slug == "find-a-tender":
                raise RuntimeError("private upstream detail")
            return self.fetch(slug)

        with patch.object(discovery, "fetch_source", side_effect=partial):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(
            [s["status"] for s in result["sources"]], ["success", "unavailable"]
        )
        self.assertEqual(result["sources"][1]["error_code"], "source_unavailable")
        self.assertNotIn("private upstream detail", str(result))
        self.assertEqual(
            {row["source"]: row["freshly_fetched"] for row in result["items"]},
            {"contracts-finder": True, "find-a-tender": False},
        )

    def test_both_failures_return_recorded_results(self):
        ingestion.ingest_tenders(
            self.engine,
            discovery.SOURCES["contracts-finder"],
            ParsedListing([self.contracts]),
        )
        with patch.object(
            discovery, "fetch_source", side_effect=RuntimeError("upstream")
        ):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(result["result_count"], 1)
        self.assertFalse(result["items"][0]["freshly_fetched"])
        self.assertEqual(
            [s["status"] for s in result["sources"]], ["unavailable", "unavailable"]
        )

    def test_empty_query_does_not_fetch(self):
        with patch.object(
            discovery, "fetch_source", side_effect=AssertionError("must not fetch")
        ):
            result = discovery.search(self.engine, q=" ")
        self.assertEqual(result["mode"], "recorded")
        self.assertEqual(result["sources"], [])

    def test_source_batch_is_bounded_and_deduplicated_before_ingestion(self):
        duplicates = [
            self.contracts,
            self.contracts.model_copy(
                update={
                    "source_url": "https://www.contractsfinder.service.gov.uk/Notice/other"
                }
            ),
        ]
        records = duplicates + [
            record("contracts-finder", f"contract-{n}", f"Cloud {n}")
            for n in range(2, 30)
        ]
        with (
            patch.object(
                discovery.contracts_finder, "fetch_releases", return_value={}
            ) as fetch,
            patch.object(
                discovery.contracts_finder,
                "parse_releases",
                return_value=ParsedListing(records),
            ),
        ):
            listing, fetched_at = discovery.fetch_source("contracts-finder")
        self.assertEqual(len(listing.records), discovery.MAX_RESULTS_PER_SOURCE)
        self.assertEqual(len({item.external_id for item in listing.records}), 20)
        self.assertEqual(
            fetch.call_args.kwargs["timeout"], discovery.LIVE_REQUEST_TIMEOUT_SECONDS
        )
        self.assertIsNotNone(fetched_at.tzinfo)

    def test_source_fetches_overlap(self):
        barrier = Barrier(2, timeout=2)

        def concurrent(slug):
            barrier.wait()
            return self.fetch(slug)

        with patch.object(discovery, "fetch_source", side_effect=concurrent):
            result = discovery.search(self.engine, q="cloud")
        self.assertEqual(len(result["sources"]), 2)
        self.assertTrue(all(item["status"] == "success" for item in result["sources"]))

    def test_api_contract_and_sanitized_errors(self):
        settings = Settings(_env_file=None, postgres_password="test-only")
        with (
            patch("app.main.create_database_engine", return_value=self.engine),
            patch("app.main.Settings", return_value=settings),
            patch.object(discovery, "fetch_source", side_effect=self.fetch),
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

        def partial(slug):
            if slug == "find-a-tender":
                raise RuntimeError("private upstream detail")
            return self.fetch(slug)

        with (
            patch("app.main.create_database_engine", return_value=self.engine),
            patch("app.main.Settings", return_value=settings),
            patch.object(discovery, "fetch_source", side_effect=partial),
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
                "fetch_source",
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
