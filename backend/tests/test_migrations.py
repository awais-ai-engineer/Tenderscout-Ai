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
    def test_0007_pipeline_tables_partial_index_and_restrict(self):
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0006:0007", sql=True
            )
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertIn("CREATE UNIQUE INDEX uq_pipeline_active_source", sql)
        self.assertIn("WHERE status IN ('queued', 'running')", sql)
        self.assertIn("CONSTRAINT uq_pipeline_stage_identity UNIQUE", sql)
        self.assertIn("metrics JSONB", sql)
        self.assertIn("scope_ids JSONB", sql)
        self.assertIn(
            "FOREIGN KEY(pipeline_run_id) REFERENCES pipeline_runs (id) "
            "ON DELETE RESTRICT",
            sql,
        )
        self.assertNotIn("ALTER TABLE", sql)
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.downgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0007:0006", sql=True
            )
        self.assertLess(
            output.getvalue().index("DROP TABLE pipeline_stage_runs"),
            output.getvalue().index("DROP TABLE pipeline_runs"),
        )

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
        self.assertIn("'0005'", sql)
        self.assertIn("'0006'", sql)
        self.assertIn("'0007'", sql)

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

    def test_0005_vector_extension_and_rag_tables(self):
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0004:0005", sql=True
            )
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sql)
        self.assertIn("embedding VECTOR(1536)", sql)
        self.assertIn("citations JSONB", sql)
        self.assertIn("CONSTRAINT uq_questions_identity UNIQUE", sql)
        self.assertNotIn("hnsw", sql.lower())
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.downgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0005:0004", sql=True
            )
        sql = output.getvalue()
        self.assertLess(
            sql.index("DROP TABLE chunk_embeddings"),
            sql.index("DROP TABLE document_chunks"),
        )
        self.assertIn("DROP TABLE tender_questions", sql)
        self.assertNotIn("DROP EXTENSION", sql)

    def test_0006_only_adds_revision_and_change_tables_without_backfill(self):
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.upgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0005:0006", sql=True
            )
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        self.assertIn("CREATE TABLE tender_revisions", sql)
        self.assertIn("CREATE TABLE tender_metadata_change_sets", sql)
        self.assertIn("CREATE TABLE document_analysis_change_sets", sql)
        self.assertIn("changes JSONB", sql)
        self.assertNotIn("ALTER TABLE", sql)
        self.assertNotIn("INSERT INTO tender", sql)
        self.assertNotIn("snapshot_hash)", sql)
        output = StringIO()
        with patch.dict(
            os.environ, {"POSTGRES_PASSWORD": "offline-test-only"}, clear=True
        ):
            command.downgrade(
                Config(str(CONFIG_FILE), output_buffer=output), "0006:0005", sql=True
            )
        sql = output.getvalue()
        self.assertLess(
            sql.index("DROP TABLE tender_metadata_change_sets"),
            sql.index("DROP TABLE tender_revisions"),
        )
        self.assertIn("DROP TABLE document_analysis_change_sets", sql)
