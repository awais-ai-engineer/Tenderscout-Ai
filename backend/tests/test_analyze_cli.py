import os
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.analyze import main
from app.core.config import Settings
from app.services.analysis import AnalysisResult, DocumentVersionNotFound, prepare_text


class AnalyzeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        stack.enter_context(patch("app.analyze.logging.basicConfig"))
        self.settings = Settings(
            _env_file=None,
            postgres_password="test-db-secret",
            openai_api_key="test-api-secret",
            ai_model="test-model",
        )
        self.config = stack.enter_context(
            patch("app.analyze.Settings", return_value=self.settings)
        )
        self.engine = stack.enter_context(patch("app.analyze.create_database_engine"))
        self.client = stack.enter_context(patch("app.analyze.OpenAIStructuredClient"))
        self.analyze = stack.enter_context(patch("app.analyze.analyze_document"))
        self.prepare = stack.enter_context(patch("app.analyze.prepare_document"))
        self.output = stack.enter_context(redirect_stdout(StringIO()))
        stack.enter_context(
            patch(
                "socket.create_connection",
                side_effect=AssertionError("External LLM call forbidden"),
            )
        )

    def test_success_outputs_only_status_and_closes_resources(self) -> None:
        self.analyze.return_value = AnalysisResult(
            12, "completed", 7, "test-model", False
        )
        self.assertEqual(main(["--document-version-id", "12"]), 0)
        self.assertEqual(
            self.output.getvalue().strip(),
            "document_version_id=12 status=completed analysis_id=7 "
            "model=test-model reused=false",
        )
        self.client.return_value.close.assert_called_once()
        self.engine.return_value.dispose.assert_called_once()
        self.assertNotIn("test-api-secret", self.output.getvalue())

    def test_failed_reused_result_has_nonzero_exit_and_truthful_status(self) -> None:
        self.analyze.return_value = AnalysisResult(12, "failed", 7, "test-model", True)
        self.assertEqual(main(["--document-version-id", "12"]), 1)
        self.assertIn("status=failed", self.output.getvalue())
        self.assertIn("reused=true", self.output.getvalue())

    def test_prepare_only_does_not_require_key_or_model(self) -> None:
        self.config.return_value = Settings(
            _env_file=None, postgres_password="test-only"
        )
        self.prepare.return_value = prepare_text("Sensitive document text", 128)
        self.assertEqual(main(["--document-version-id", "12", "--prepare-only"]), 0)
        self.client.assert_not_called()
        self.analyze.assert_not_called()
        self.assertIn("status=prepared input_chars=23", self.output.getvalue())
        self.assertNotIn("Sensitive", self.output.getvalue())
        self.engine.return_value.dispose.assert_called_once()

    def test_missing_ai_configuration_fails_before_client_or_database(self) -> None:
        for field in ("ai_model", "openai_api_key"):
            self.config.return_value = self.settings.model_copy(update={field: None})
            with (
                self.subTest(field=field),
                self.assertLogs("app.analyze", level="ERROR"),
            ):
                self.assertEqual(main(["--document-version-id", "12"]), 1)
        self.client.assert_not_called()
        self.engine.assert_not_called()

    def test_skipped_prepare_result_does_not_call_provider(self) -> None:
        self.prepare.return_value = None
        self.assertEqual(main(["--document-version-id", "12", "--prepare-only"]), 0)
        self.assertIn("status=skipped", self.output.getvalue())
        self.client.assert_not_called()

    def test_missing_version_is_reported_and_resources_close(self) -> None:
        self.analyze.side_effect = DocumentVersionNotFound(
            "Document version does not exist"
        )
        with self.assertLogs("app.analyze", level="ERROR"):
            self.assertEqual(main(["--document-version-id", "12"]), 1)
        self.client.return_value.close.assert_called_once()
        self.engine.return_value.dispose.assert_called_once()

    def test_database_failure_hides_details_and_prints_no_success(self) -> None:
        self.analyze.side_effect = OperationalError(
            "INSERT", {}, RuntimeError("test-api-secret test-db-secret")
        )
        with self.assertLogs("app.analyze", level="ERROR") as logs:
            self.assertEqual(main(["--document-version-id", "12"]), 1)
        self.assertNotIn("test-api-secret", " ".join(logs.output))
        self.assertNotIn("test-db-secret", " ".join(logs.output))
        self.assertEqual(self.output.getvalue(), "")
        self.engine.return_value.dispose.assert_called_once()

    def test_explicit_positive_document_version_id_is_required(self) -> None:
        for args in (
            [],
            ["--document-version-id", "0"],
            ["--document-version-id", "-1"],
        ):
            with (
                self.subTest(args=args),
                patch("sys.stderr", StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main(args)
            self.assertEqual(error.exception.code, 2)
        self.engine.assert_not_called()


class AIConfigurationTests(unittest.TestCase):
    def test_ai_is_optional_for_backend_and_prepare_only(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None, postgres_password="test-only")
        self.assertIsNone(settings.openai_api_key)
        self.assertIsNone(settings.ai_model)
        self.assertEqual(settings.ai_max_input_chars, 60000)

    def test_ai_key_redaction_and_environment_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POSTGRES_PASSWORD": "test-db",
                "OPENAI_API_KEY": "test-api-secret",
                "AI_MODEL": "configured-model",
                "AI_MAX_INPUT_CHARS": "1000",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.ai_model, "configured-model")
        self.assertEqual(settings.ai_max_input_chars, 1000)
        self.assertEqual(settings.openai_api_key.get_secret_value(), "test-api-secret")
        self.assertNotIn("test-api-secret", repr(settings))
        self.assertNotIn("test-api-secret", settings.model_dump_json())

    def test_invalid_ai_configuration_is_rejected_without_input_leak(self) -> None:
        for values in (
            {"ai_model": ""},
            {"ai_model": "private model\n"},
            {"ai_max_input_chars": 127},
            {"openai_api_key": " "},
        ):
            with (
                self.subTest(values=values),
                patch.dict(os.environ, {}, clear=True),
                self.assertRaises(ValidationError) as error,
            ):
                Settings(_env_file=None, postgres_password="test-only", **values)
            self.assertNotIn("private model", str(error.exception))
