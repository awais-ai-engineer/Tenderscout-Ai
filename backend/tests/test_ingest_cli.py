import json
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from app.ingest import main
from app.scrapers.find_tender import SourceFetchError
from app.services.ingestion import IngestionResult

FIXTURE = Path(__file__).parent / "fixtures" / "find_tender_listing.html"


class IngestCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.ingest.logging.basicConfig"))
        self.fetch = self.stack.enter_context(
            patch(
                "app.sources.connectors.find_tender.fetch_listing",
                return_value=FIXTURE.read_text(encoding="utf-8"),
            )
        )
        self.settings = self.stack.enter_context(patch("app.ingest.Settings"))
        self.engine = self.stack.enter_context(
            patch("app.ingest.create_database_engine")
        )
        self.ingest = self.stack.enter_context(patch("app.ingest.ingest_tenders"))
        self.output = self.stack.enter_context(redirect_stdout(StringIO()))

    def test_fetch_only_never_initializes_database_configuration(self) -> None:
        with patch("sys.argv", ["app.ingest", "--fetch-only"]):
            self.assertEqual(main(), 0)
        self.settings.assert_not_called()
        self.engine.assert_not_called()
        self.ingest.assert_not_called()
        self.assertIn("mode: fetch-only (no database writes)", self.output.getvalue())
        self.assertIn("valid: 2", self.output.getvalue())

    def test_success_prints_committed_result_and_disposes_engine(self) -> None:
        self.ingest.return_value = IngestionResult(discovered=3, created=2, skipped=1)
        with patch("sys.argv", ["app.ingest"]):
            self.assertEqual(main(), 0)
        self.engine.return_value.dispose.assert_called_once()
        self.assertIn("created: 2\nchanged: 0\nunchanged: 0", self.output.getvalue())

    def test_database_failure_does_not_print_uncommitted_counts_or_credentials(
        self,
    ) -> None:
        secret = "test-secret-that-must-not-be-logged"
        self.ingest.side_effect = OperationalError("insert", {}, RuntimeError(secret))
        with (
            patch("sys.argv", ["app.ingest"]),
            self.assertLogs("app.ingest", level="ERROR") as logs,
        ):
            self.assertEqual(main(), 1)
        self.engine.return_value.dispose.assert_called_once()
        self.assertNotIn(secret, " ".join(logs.output))
        self.assertEqual(self.output.getvalue(), "")

    def test_fetch_failure_prevents_ingestion(self) -> None:
        self.fetch.side_effect = SourceFetchError("Public source request failed")
        with (
            patch("sys.argv", ["app.ingest"]),
            self.assertLogs("app.ingest", level="ERROR"),
        ):
            self.assertEqual(main(), 1)
        self.engine.assert_not_called()
        self.ingest.assert_not_called()

    def test_partial_failure_has_nonzero_exit_code(self) -> None:
        self.ingest.return_value = IngestionResult(
            discovered=3, created=1, failed=1, skipped=1
        )
        with patch("sys.argv", ["app.ingest"]):
            self.assertEqual(main(), 1)
        self.assertIn("failed: 1", self.output.getvalue())

    def test_contracts_finder_fetch_only_selects_json_adapter(self) -> None:
        payload = json.loads(
            FIXTURE.with_name("contracts_finder.json").read_text(encoding="utf-8")
        )
        with (
            patch(
                "sys.argv",
                ["app.ingest", "--source", "contracts-finder", "--fetch-only"],
            ),
            patch(
                "app.sources.connectors.contracts_finder.fetch_releases",
                return_value=payload,
            ) as fetch,
        ):
            self.assertEqual(main(), 0)
        fetch.assert_called_once()
        self.fetch.assert_not_called()
        self.engine.assert_not_called()
        self.settings.assert_not_called()
        self.assertIn("source: contracts-finder", self.output.getvalue())
        self.assertIn("valid: 2", self.output.getvalue())

    def test_contracts_finder_passes_its_source_to_ingestion(self) -> None:
        self.ingest.return_value = IngestionResult(discovered=0)
        with (
            patch("sys.argv", ["app.ingest", "--source", "contracts-finder"]),
            patch(
                "app.sources.connectors.contracts_finder.fetch_releases",
                return_value={"releases": []},
            ),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(self.ingest.call_args.args[1].slug, "contracts-finder")
        self.fetch.assert_not_called()

    def test_unknown_source_is_a_cli_error_before_fetch(self) -> None:
        with (
            patch("sys.argv", ["app.ingest", "--source", "unknown"]),
            patch("sys.stderr", StringIO()) as stderr,
            self.assertRaises(SystemExit) as error,
        ):
            main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())
        self.fetch.assert_not_called()
