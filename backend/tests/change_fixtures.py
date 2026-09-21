from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, attributes

from app.ai.schemas import TenderAnalysisOutput
from app.models import (
    Base,
    DocumentVersion,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
)
from app.schemas.source import SourceCreate
from app.scrapers.records import ScrapedTender


def output(**values):
    data = {
        name: []
        for name in TenderAnalysisOutput.model_fields
        if name not in {"summary", "summary_evidence"}
    }
    data.update(summary=None, summary_evidence=[])
    return TenderAnalysisOutput.model_validate(data | values)


def item(value, evidence=None):
    return {"value": value, "evidence": evidence or value}


def contact(**values):
    return (
        {name: None for name in ("name", "organization", "email", "phone", "role")}
        | {"evidence": "Synthetic contact details"}
        | values
    )


class ChangeDatabaseMixin:
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.transactions = 0
        self.serial = 0

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            self.transactions += 1

        @event.listens_for(self.engine, "commit")
        @event.listens_for(self.engine, "rollback")
        def end(connection):
            self.transactions -= 1

        def restore_offsets(session, row):
            if session.bind is self.engine and isinstance(row, Tender):
                for name in ("published_at", "deadline"):
                    value = getattr(row, name)
                    if value and value.tzinfo is None:
                        attributes.set_committed_value(
                            row, name, value.replace(tzinfo=UTC)
                        )

        event.listen(Session, "loaded_as_persistent", restore_offsets)
        self.addCleanup(event.remove, Session, "loaded_as_persistent", restore_offsets)
        Base.metadata.create_all(self.engine)
        self.source = SourceCreate(
            name="Synthetic change fixture",
            slug="changes",
            base_url="https://example.test",
        )
        self.record = ScrapedTender(
            external_id="synthetic-1",
            title="Initial tender",
            organization="Authority A",
            deadline=datetime(2026, 10, 10, tzinfo=UTC),
            source_url="https://example.test/tender",
        )
        for target in (
            "socket.socket.connect",
            "socket.create_connection",
            "httpx.Client.send",
            "app.ai.embeddings.OpenAIEmbeddingClient.embed",
            "app.ai.openai_client.OpenAIStructuredClient.generate",
        ):
            blocker = patch(
                target,
                side_effect=AssertionError("Diffing must not call external services"),
            )
            blocker.start()
            self.addCleanup(blocker.stop)

    def legacy_tender(self, **values):
        with Session(self.engine) as session, session.begin():
            source = session.scalar(
                select(Source).where(Source.slug == self.source.slug)
            )
            if source is None:
                source = Source(
                    **(
                        self.source.model_dump()
                        | {"base_url": str(self.source.base_url)}
                    )
                )
                session.add(source)
                session.flush()
            row = Tender(
                source_id=source.id,
                **(
                    self.record.model_dump()
                    | {
                        "source_url": str(self.record.source_url),
                        "last_seen_at": datetime(2026, 9, 1, tzinfo=UTC),
                    }
                    | values
                ),
            )
            session.add(row)
            session.flush()
            return row.id

    def add_document(self, tender_id):
        self.serial += 1
        with Session(self.engine) as session, session.begin():
            row = TenderDocument(
                tender_id=tender_id,
                source_url=f"https://example.test/doc/{self.serial}",
            )
            session.add(row)
            session.flush()
            return row.id

    def add_version(self, document_id, downloaded_at):
        self.serial += 1
        with Session(self.engine) as session, session.begin():
            row = DocumentVersion(
                document_id=document_id,
                content_hash=f"{self.serial:064x}",
                byte_size=1,
                storage_path="synthetic.pdf",
                extraction_status="extracted",
                extracted_text="Synthetic source",
                downloaded_at=downloaded_at,
            )
            session.add(row)
            session.flush()
            return row.id

    def add_analysis(self, version_id, data=None, **values):
        self.serial += 1
        with Session(self.engine) as session, session.begin():
            row = TenderAnalysis(
                **(
                    dict(
                        document_version_id=version_id,
                        analysis_schema_version="v1",
                        provider="synthetic",
                        model="test-model",
                        prompt_version="v1",
                        input_hash=f"{self.serial:064x}",
                        status="completed",
                    )
                    | (data or output()).model_dump()
                    | values
                )
            )
            session.add(row)
            session.flush()
            return row.id

    def snapshot(self, model, row_id):
        with Session(self.engine) as session:
            row = session.get(model, row_id)
            return {
                column.name: getattr(row, column.name) for column in model.__table__.c
            }
