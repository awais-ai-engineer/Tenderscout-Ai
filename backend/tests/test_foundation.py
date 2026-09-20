import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.main import app


class FoundationTests(unittest.TestCase):
    def test_health_and_lifespan_without_external_services(self) -> None:
        with (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only-password"}),
            TestClient(app) as client,
        ):
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})
            self.assertEqual(app.state.db_engine.dialect.name, "postgresql")

    def test_environment_overrides_dotenv(self) -> None:
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "POSTGRES_PASSWORD=dotenv-password\nPOSTGRES_PORT=5433\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"POSTGRES_PORT": "5434"}, clear=True):
                settings = Settings(_env_file=env_file)
            self.assertEqual(settings.postgres_port, 5434)
            self.assertEqual(
                settings.postgres_password.get_secret_value(), "dotenv-password"
            )

    def test_secrets_are_redacted_and_url_handles_special_characters(self) -> None:
        password = "test@password:/?#"
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(
                _env_file=None,
                postgres_password=password,
                redis_password=password,
            )
        engine = create_database_engine(settings)
        try:
            self.assertEqual(engine.url.password, password)
            for rendered in (
                repr(settings),
                settings.model_dump_json(),
                str(engine.url),
            ):
                self.assertNotIn(password, rendered)
        finally:
            engine.dispose()

    def test_invalid_configuration_hides_input(self) -> None:
        sensitive_input = "sensitive-invalid-port"
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(ValidationError) as error,
        ):
            Settings(
                _env_file=None,
                postgres_password="test-password",
                postgres_port=sensitive_input,
            )
        self.assertNotIn(sensitive_input, str(error.exception))

    def test_missing_or_empty_password_fails(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for values in ({}, {"postgres_password": ""}):
                with self.subTest(values=values), self.assertRaises(ValidationError):
                    Settings(_env_file=None, **values)
