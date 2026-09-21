import os
import re
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from alembic import command, context
from app.models import Base

CONFIG_FILE = Path(__file__).resolve().parents[1] / "alembic.ini"


class MigrationTests(unittest.TestCase):
    def test_postgresql_upgrade_sql_matches_model_metadata(self) -> None:
        output = StringIO()
        config = Config(str(CONFIG_FILE), output_buffer=output)
        with (
            patch.dict(
                os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
            ),
            patch.object(context, "configure", wraps=context.configure) as configure,
        ):
            command.upgrade(config, "head", sql=True)
        self.assertIs(configure.call_args.kwargs["target_metadata"], Base.metadata)
        sql = output.getvalue()
        for table in Base.metadata.sorted_tables:
            expected = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            actual = re.search(rf"CREATE TABLE {table.name} \(\n(.*?)\n\);", sql, re.S)
            self.assertIsNotNone(actual)
            self.assertEqual(
                sorted(line.strip().rstrip(",") for line in actual[1].splitlines()),
                sorted(
                    line.strip().rstrip(",")
                    for line in expected.strip().splitlines()[1:-1]
                ),
            )
            for index in table.indexes:
                expected = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
                self.assertIn(" ".join(expected.split()), sql)
        self.assertNotIn("offline-test-only", sql)
        self.assertIn("'0001'", sql)
        self.assertIn("'0002'", sql)
        self.assertIn("'0003'", sql)
        self.assertIn("'0004'", sql)

    def test_postgresql_downgrade_sql_drops_child_table_first(self) -> None:
        output = StringIO()
        config = Config(str(CONFIG_FILE), output_buffer=output)
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.downgrade(config, "head:base", sql=True)
        sql = output.getvalue()
        self.assertLess(
            sql.index("DROP TABLE tender_matches"),
            sql.index("DROP TABLE tender_analyses"),
        )
        self.assertLess(
            sql.index("DROP TABLE tender_matches"),
            sql.index("DROP TABLE company_profiles"),
        )
        for child in (
            "company_capabilities",
            "company_certifications",
            "company_experience",
        ):
            self.assertLess(
                sql.index(f"DROP TABLE {child}"),
                sql.index("DROP TABLE company_profiles"),
            )
        self.assertLess(
            sql.index("DROP TABLE tender_analyses"),
            sql.index("DROP TABLE document_versions"),
        )
        self.assertLess(
            sql.index("DROP TABLE document_versions"),
            sql.index("DROP TABLE tender_documents"),
        )
        self.assertLess(
            sql.index("DROP TABLE tender_documents"), sql.index("DROP TABLE tenders")
        )
        self.assertIn("DROP INDEX ix_tenders_deadline", sql)
        self.assertIn("DROP INDEX ix_tenders_source_id", sql)
        self.assertLess(
            sql.index("DROP TABLE tenders"), sql.index("DROP TABLE sources")
        )

    def test_0002_upgrade_only_creates_document_schema(self) -> None:
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0001:0002", sql=True
            )
        sql = output.getvalue()
        self.assertIn("CREATE TABLE tender_documents", sql)
        self.assertIn("CREATE TABLE document_versions", sql)
        self.assertNotIn("CREATE TABLE sources", sql)
        self.assertNotIn("CREATE TABLE tenders", sql)
        self.assertNotIn("ALTER TABLE", sql)

    def test_0003_upgrade_only_creates_analysis_schema(self) -> None:
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0002:0003", sql=True
            )
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("CREATE TABLE tender_analyses", sql)
        self.assertIn("eligibility_requirements JSONB", sql)
        self.assertIn("CONSTRAINT uq_analyses_identity UNIQUE", sql)
        self.assertNotIn("ALTER TABLE", sql)

    def test_0004_only_adds_company_and_match_tables(self):
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0003:0004", sql=True
            )
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TABLE"), 5)
        self.assertIn("company_snapshot JSONB", sql)
        self.assertIn("CONSTRAINT uq_matches_identity UNIQUE", sql)
        self.assertNotIn("ALTER TABLE", sql)
