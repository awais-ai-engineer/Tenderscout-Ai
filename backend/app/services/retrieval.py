from dataclasses import dataclass, field

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingClient, embed_batch
from app.models import ChunkEmbedding, DocumentChunk, DocumentVersion
from app.rag.chunking import CHUNKER_VERSION
from app.rag.config import EmbeddingConfig

RETRIEVAL_VERSION = "v1"


class RetrievalError(ValueError):
    pass


def normalize_question(question: str) -> str:
    if not isinstance(question, str):
        raise ValueError("Question must be text")
    normalized = question.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 1 <= len(normalized) <= 2000 or "\x00" in normalized:
        raise ValueError("Question must contain 1 to 2000 characters without NULs")
    normalized.encode("utf-8")
    return normalized


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_version_id: int
    chunk_index: int
    text: str = field(repr=False)
    distance: float
    start_char: int
    end_char: int


def scoped_embeddings(
    document_version_id: int,
    provider: str,
    config: EmbeddingConfig,
    chunker_version: str,
):
    return (
        select(DocumentChunk)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .where(
            DocumentChunk.document_version_id == document_version_id,
            DocumentChunk.chunker_version == chunker_version,
            ChunkEmbedding.provider == provider,
            ChunkEmbedding.model == config.model,
            ChunkEmbedding.dimensions == config.dimensions,
            ChunkEmbedding.input_hash == DocumentChunk.content_hash,
        )
    )


def retrieval_query(
    document_version_id: int,
    provider: str,
    config: EmbeddingConfig,
    chunker_version: str,
    vector: list[float],
    top_k: int,
):
    distance = ChunkEmbedding.embedding.cosine_distance(vector).label("distance")
    return (
        scoped_embeddings(document_version_id, provider, config, chunker_version)
        .add_columns(distance)
        .order_by(distance, DocumentChunk.chunk_index, DocumentChunk.id)
        .limit(top_k)
    )


def retrieve(
    engine: Engine,
    document_version_id: int,
    question: str,
    client: EmbeddingClient,
    *,
    embedding: EmbeddingConfig,
    top_k: int = 5,
    chunker_version: str = CHUNKER_VERSION,
) -> list[RetrievedChunk]:
    question = normalize_question(question)
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    with Session(engine) as session:
        if session.get(DocumentVersion, document_version_id) is None:
            raise RetrievalError("Document version does not exist")
        chunk_count = session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.document_version_id == document_version_id,
                DocumentChunk.chunker_version == chunker_version,
            )
        )
        embedded_count = session.scalar(
            select(func.count()).select_from(
                scoped_embeddings(
                    document_version_id, client.provider, embedding, chunker_version
                ).subquery()
            )
        )
    if not chunk_count or embedded_count != chunk_count:
        raise RetrievalError(
            "Document is not fully indexed for this chunker and embedding model"
        )
    vector = embed_batch(
        client, [question], model=embedding.model, dimensions=embedding.dimensions
    )[0]
    with Session(engine) as session:
        rows = session.execute(
            retrieval_query(
                document_version_id,
                client.provider,
                embedding,
                chunker_version,
                vector,
                top_k,
            )
        ).all()
        return [
            RetrievedChunk(
                row.id,
                row.document_version_id,
                row.chunk_index,
                row.text,
                float(distance),
                row.start_char,
                row.end_char,
            )
            for row, distance in rows
        ]
