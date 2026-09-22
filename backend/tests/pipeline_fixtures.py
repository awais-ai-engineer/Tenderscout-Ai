import os
from datetime import UTC, datetime
from unittest.mock import patch

from change_fixtures import ChangeDatabaseMixin, output
from rag_fixtures import FakeEmbeddingClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PipelineStageRun
from app.services import pipeline as p
from app.services.pipeline_steps import config_key


class FakeStructuredClient:
    provider = "synthetic"

    def __init__(self, before_call, error=None):
        self.before_call, self.error = before_call, error
        self.calls = 0
        self.closed = False

    def generate(self, **kwargs):
        self.before_call()
        self.calls += 1
        if self.error:
            raise self.error
        return output().model_dump_json()

    def close(self):
        self.closed = True


class PipelineDatabaseMixin(ChangeDatabaseMixin):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.settings = Settings(
            _env_file=None,
            openai_api_key="test-only",
            ai_model="synthetic-model",
            ai_embedding_model="synthetic-embedding",
        )
        self.tender_id = self.legacy_tender()
        self.document_id = self.add_document(self.tender_id)
        self.version_id = self.add_version(
            self.document_id, datetime(2026, 9, 1, tzinfo=UTC)
        )
        self.structured = FakeStructuredClient(
            lambda: self.assertEqual(self.transactions, 0)
        )
        self.embedder = FakeEmbeddingClient(
            before_call=lambda: self.assertEqual(self.transactions, 0)
        )

    def root(self, source="contracts-finder", trigger="manual"):
        run_id, _ = p.create_run(self.engine, source, trigger)
        return p.queued_children(self.engine, run_id, None)[0]

    def child(self, stage, entity_type="document_version", entity_id=None):
        root = self.root()
        row, run = p.claim_stage(self.engine, root)
        p.finish_stage(
            self.engine,
            root,
            row.attempt,
            p.Outcome(
                children=[
                    p.StageSpec(
                        stage,
                        entity_type,
                        entity_id or self.version_id,
                        config_key(self.settings),
                    )
                ]
            ),
        )
        child_id = p.queued_children(self.engine, run.id, root)[0]
        return p.claim_stage(self.engine, child_id)

    def rows(self, run_id):
        with Session(self.engine) as session:
            return session.scalars(
                select(PipelineStageRun)
                .where(PipelineStageRun.pipeline_run_id == run_id)
                .order_by(PipelineStageRun.id)
            ).all()
