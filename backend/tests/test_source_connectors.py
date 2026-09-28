import unittest
from unittest.mock import Mock, patch

from app.schemas.source import SourceCreate
from app.scrapers.records import ParsedListing, ScrapedTender
from app.sources.connectors import (
    SOURCE_CONNECTORS,
    SourceConnector,
    _bounded,
    connector,
    registry,
)


class SourceConnectorTests(unittest.TestCase):
    def test_registry_is_exact_and_selection_is_stable(self):
        self.assertEqual(
            set(SOURCE_CONNECTORS), {"contracts-finder", "find-a-tender", "ted"}
        )
        self.assertEqual(connector("ted").display_name, "TED")
        with self.assertRaisesRegex(ValueError, "Unsupported source"):
            connector("other")

    def test_duplicate_slugs_are_rejected(self):
        source = SourceCreate(name="One", slug="duplicate", base_url="https://one.test")
        first = SourceConnector(source, Mock(), Mock())
        second = SourceConnector(
            source.model_copy(update={"name": "Two"}), Mock(), Mock()
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            registry(first, second)

    def test_existing_connectors_preserve_parsers_and_contract(self):
        record = ScrapedTender(
            external_id="one",
            title="Cloud services",
            source_url="https://example.test/one",
        )
        for slug, module, fetch_name, parse_name in (
            (
                "contracts-finder",
                "app.sources.connectors.contracts_finder",
                "fetch_releases",
                "parse_releases",
            ),
            (
                "find-a-tender",
                "app.sources.connectors.find_tender",
                "fetch_listing",
                "parse_listing",
            ),
        ):
            with self.subTest(source=slug):
                with (
                    patch(f"{module}.{fetch_name}", return_value=object()) as fetch,
                    patch(
                        f"{module}.{parse_name}", return_value=ParsedListing([record])
                    ),
                ):
                    listing = connector(slug).search(
                        Mock(), "cloud", limit=5, timeout=3.0
                    )
                self.assertEqual(listing.records, [record])
                self.assertEqual(fetch.call_args.kwargs["timeout"], 3.0)

    def test_connector_bounds_and_deduplicates_by_strong_identity(self):
        records = [
            ScrapedTender(
                external_id=str(index),
                title=f"Tender {index}",
                source_url=f"https://example.test/{index}",
            )
            for index in range(4)
        ]
        records.insert(1, records[0])
        listing = _bounded(ParsedListing(records), 2)
        self.assertEqual([record.external_id for record in listing.records], ["0", "1"])
        self.assertEqual(
            (listing.limited, listing.skipped, listing.discovered), (2, 3, 5)
        )


if __name__ == "__main__":
    unittest.main()
