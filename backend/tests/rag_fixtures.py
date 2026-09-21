import json
import math
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import BinaryExpression

from app.models import Base, DocumentVersion, Source, Tender, TenderDocument
from app.rag.config import VECTOR_DIMENSIONS, ChunkConfig, EmbeddingConfig

EMBEDDING = EmbeddingConfig(model="synthetic-embedding")
CHUNKING = ChunkConfig()
SOURCE_A = "Submission deadline: 1 June 2027. Mandatory certification: ISO 27001."
SOURCE_B = "Submission deadline: 1 July 2027."


def vector(x=1.0, y=0.0):
    return [x, y] + [0.0] * (VECTOR_DIMENSIONS - 2)


@compiles(BinaryExpression, "sqlite")
def sqlite_test_distance(element, compiler, **kwargs):
    # Test-only translation: production PostgreSQL retains pgvector's real <=> operator.
    if getattr(element.operator, "opstring", None) == "<=>":
        return (
            f"test_cosine_distance({compiler.process(element.left, **kwargs)}, "
            f"{compiler.process(element.right, **kwargs)})"
        )
    return compiler.visit_binary(element, **kwargs)


def cosine(left, right):
    a, b = json.loads(left), json.loads(right)
    return 1 - math.fsum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(x * x for x in b))
    )


class FakeEmbeddingClient:
    provider = "synthetic"

    def __init__(self, before_call=lambda: None, vectors=None, error=None):
        self.calls = []
        self.before_call = before_call
        self.vectors = vectors
        self.error = error

    def embed(self, texts, *, model, dimensions):
        self.before_call()
        self.calls.append((list(texts), model, dimensions))
        if self.error:
            raise self.error
        return self.vectors if self.vectors is not None else [vector() for _ in texts]

    def close(self):
        pass


class FakeAnswerClient:
    provider = "synthetic"

    def __init__(self, before_call=lambda: None, response=None, error=None):
        self.calls = []
        self.before_call = before_call
        self.response = response
        self.error = error

    def generate(self, **kwargs):
        self.before_call()
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if self.response is not None:
            return self.response
        chunks = json.loads(kwargs["text"].split("UNTRUSTED_TENDER_CONTEXT_JSON:\n")[1])
        quote = chunks[0]["text"][:100].strip()
        return json.dumps(
            {
                "answer": quote,
                "citations": [{"chunk_id": chunks[0]["chunk_id"], "quote": quote}],
                "insufficient_evidence": False,
            }
        )

    def close(self):
        pass


class RagDatabaseMixin:
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.transactions = 0

        @event.listens_for(self.engine, "connect")
        def connect(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.create_function("test_cosine_distance", 2, cosine)

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            self.transactions += 1

        @event.listens_for(self.engine, "commit")
        @event.listens_for(self.engine, "rollback")
        def end(connection):
            self.transactions -= 1

        Base.metadata.create_all(self.engine)
        self.version_id = self.add_version(SOURCE_A)
        self.other_version_id = self.add_version(SOURCE_B)
        self.embedder = FakeEmbeddingClient(
            before_call=lambda: self.assertEqual(self.transactions, 0)
        )
        self.answerer = FakeAnswerClient(
            before_call=lambda: self.assertEqual(self.transactions, 0)
        )
        for target in ("socket.socket.connect", "socket.create_connection"):
            blocker = patch(
                target, side_effect=AssertionError("External network forbidden")
            )
            blocker.start()
            self.addCleanup(blocker.stop)

    def add_version(self, text, status="extracted"):
        with Session(self.engine) as session, session.begin():
            source = Source(
                name="Synthetic",
                slug=str(id(text)) + status,
                base_url="https://example.test",
            )
            tender = Tender(
                source=source,
                title="Synthetic",
                source_url="https://example.test/tender",
            )
            document = TenderDocument(
                tender=tender, source_url="https://example.test/document"
            )
            version = DocumentVersion(
                document=document,
                content_hash="a" * 64,
                byte_size=1,
                storage_path="synthetic.pdf",
                extraction_status=status,
                extracted_text=text,
            )
            session.add(version)
            session.flush()
            return version.id
