import json
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from app.documents import main
from app.scrapers.errors import SourceFetchError
from app.services.documents import DocumentResult


class DocumentsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("app.documents.logging.basicConfig"))
        fixture = Path(__file__).parent / "fixtures" / "contracts_finder_documents.json"
        self.fetch = stack.enter_context(
            patch(
                "app.documents.fetch_releases",
                return_value=json.loads(fixture.read_text(encoding="utf-8")),
            )
        )
        self.settings = stack.enter_context(patch("app.documents.Settings"))
        self.engine = stack.enter_context(patch("app.documents.create_database_engine"))
        self.process = stack.enter_context(patch("app.documents.process_documents"))
        self.output = stack.enter_context(redirect_stdout(StringIO()))
        stack.enter_context(
            patch(
                "httpx.Client.send",
                side_effect=AssertionError("Unexpected network call"),
            )
        )

    def test_fetch_only_does_not_configure_database_download_or_write(self) -> None:
        with (
            patch("pathlib.Path.mkdir", side_effect=AssertionError("Dry run writes")),
            patch(
                "app.services.documents.download_pdf",
                side_effect=AssertionError("Dry run downloads"),
            ),
        ):
            self.assertEqual(main(["--source", "contracts-finder", "--fetch-only"]), 0)
        self.settings.assert_not_called()
        self.engine.assert_not_called()
        self.process.assert_not_called()
        self.fetch.assert_called_once()
        self.assertIn(
            "discovered=3 supported_pdfs=1 unsupported_or_external=2 failed=0",
            self.output.getvalue(),
        )

    def test_success_and_failure_results_dispose_engine(self) -> None:
        for failed in (0, 1):
            self.process.return_value = DocumentResult(
                discovered=1, versions_created=1, failed=failed
            )
            self.assertEqual(main([]), failed)
        self.assertEqual(self.engine.return_value.dispose.call_count, 2)
        self.assertIn("versions_created=1", self.output.getvalue())

    def test_database_error_disposes_engine_and_hides_details(self) -> None:
        self.process.side_effect = OperationalError(
            "query", {}, RuntimeError("sensitive-password")
        )
        with self.assertLogs("app.documents", level="ERROR") as logs:
            self.assertEqual(main([]), 1)
        self.engine.return_value.dispose.assert_called_once()
        self.assertNotIn("sensitive-password", " ".join(logs.output))
        self.assertEqual(self.output.getvalue(), "")

    def test_fetch_error_stops_before_database(self) -> None:
        self.fetch.side_effect = SourceFetchError("HTTP failure")
        with self.assertLogs("app.documents", level="ERROR"):
            self.assertEqual(main([]), 1)
        self.engine.assert_not_called()

    def test_discovery_failure_returns_nonzero(self) -> None:
        self.fetch.return_value = {
            "releases": [{"tender": {"documents": [{"url": "bad"}]}}]
        }
        self.assertEqual(main(["--fetch-only"]), 1)
        self.assertIn("failed=1", self.output.getvalue())

    def test_find_a_tender_is_not_supported(self) -> None:
        with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit) as error:
            main(["--source", "find-a-tender"])
        self.assertEqual(error.exception.code, 2)
        self.fetch.assert_not_called()
