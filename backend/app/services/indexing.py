from dataclasses import dataclass

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingClient, embed_batch
from app.models import ChunkEmbedding, DocumentChunk, DocumentVersion
from app.rag.chunking import CHUNKER_VERSION, PreparedChunk, chunk_text
from app.rag.config import ChunkConfig, EmbeddingConfig
from app.services.analysis import DocumentVersionNotFound


@dataclass(frozen=True)
class IndexResult:
    document_version_id: int
    chunks_created: int
    chunks_reused: int
    embeddings_created: int
    embeddings_reused: int
    model: str
    skipped: bool = False


def prepare_index(
    engine: Engine, document_version_id: int, config: ChunkConfig
) -> list[PreparedChunk]:
    with Session(engine) as session:
        version = session.get(DocumentVersion, document_version_id)
        if version is None:
            raise DocumentVersionNotFound("Document version does not exist")
        text = (
            version.extracted_text if version.extraction_status == "extracted" else None
        )
    return chunk_text(text, config) if text else []


def persist_chunks(
    engine: Engine,
    document_version_id: int,
    chunks: list[PreparedChunk],
    config: ChunkConfig,
    chunker_version: str,
) -> tuple[list[int], int]:
    for attempt in range(2):
        try:
            with Session(engine) as session, session.begin():
                session.execute(
                    select(DocumentVersion.id)
                    .where(DocumentVersion.id == document_version_id)
                    .with_for_update()
                ).scalar_one()
                existing = session.scalars(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_version_id == document_version_id,
                        DocumentChunk.chunker_version == chunker_version,
                    )
                    .order_by(DocumentChunk.chunk_index)
                ).all()
                if existing:
                    if len(existing) != len(chunks) or any(
                        (
                            row.chunk_index,
                            row.text,
                            row.content_hash,
                            row.start_char,
                            row.end_char,
                            row.chunk_size,
                            row.chunk_overlap,
                        )
                        != (
                            chunk.chunk_index,
                            chunk.text,
                            chunk.content_hash,
                            chunk.start_char,
                            chunk.end_char,
                            config.size,
                            config.overlap,
                        )
                        for row, chunk in zip(existing, chunks, strict=True)
                    ):
                        raise ValueError(
                            "Chunk set differs; bump chunker version "
                            "instead of overwriting"
                        )
                    return [row.id for row in existing], 0
                rows = [
                    DocumentChunk(
                        document_version_id=document_version_id,
                        chunker_version=chunker_version,
                        chunk_size=config.size,
                        chunk_overlap=config.overlap,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        content_hash=chunk.content_hash,
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                    )
                    for chunk in chunks
                ]
                session.add_all(rows)
                session.flush()
                return [row.id for row in rows], len(rows)
        except IntegrityError:
            if attempt:
                raise
    raise RuntimeError("Chunk persistence did not complete")


def embedding_query(chunk_ids: list[int], provider: str, config: EmbeddingConfig):
    return select(ChunkEmbedding.chunk_id, ChunkEmbedding.input_hash).where(
        ChunkEmbedding.chunk_id.in_(chunk_ids),
        ChunkEmbedding.provider == provider,
        ChunkEmbedding.model == config.model,
        ChunkEmbedding.dimensions == config.dimensions,
    )


def persist_embeddings(
    engine: Engine,
    document_version_id: int,
    batch: list[tuple[int, PreparedChunk]],
    vectors: list[list[float]],
    provider: str,
    config: EmbeddingConfig,
) -> int:
    for attempt in range(2):
        try:
            with Session(engine) as session, session.begin():
                session.execute(
                    select(DocumentVersion.id)
                    .where(DocumentVersion.id == document_version_id)
                    .with_for_update()
                ).scalar_one()
                existing = {
                    row.chunk_id: row.input_hash
                    for row in session.execute(
                        embedding_query(
                            [chunk_id for chunk_id, _ in batch], provider, config
                        )
                    )
                }
                created = 0
                for (chunk_id, chunk), vector in zip(batch, vectors, strict=True):
                    if chunk_id in existing:
                        if existing[chunk_id] != chunk.content_hash:
                            raise ValueError(
                                "Stored embedding hash differs from immutable chunk"
                            )
                        continue
                    session.add(
                        ChunkEmbedding(
                            chunk_id=chunk_id,
                            provider=provider,
                            model=config.model,
                            dimensions=config.dimensions,
                            embedding=vector,
                            input_hash=chunk.content_hash,
                        )
                    )
                    created += 1
                session.flush()
                return created
        except IntegrityError:
            if attempt:
                raise
    raise RuntimeError("Embedding persistence did not complete")


def index_document(
    engine: Engine,
    document_version_id: int,
    client: EmbeddingClient,
    *,
    embedding: EmbeddingConfig,
    chunking: ChunkConfig,
    chunker_version: str = CHUNKER_VERSION,
) -> IndexResult:
    chunks = prepare_index(engine, document_version_id, chunking)
    if not chunks:
        return IndexResult(
            document_version_id, 0, 0, 0, 0, embedding.model, skipped=True
        )
    ids, created_chunks = persist_chunks(
        engine, document_version_id, chunks, chunking, chunker_version
    )
    with Session(engine) as session:
        existing = {
            row.chunk_id: row.input_hash
            for row in session.execute(embedding_query(ids, client.provider, embedding))
        }
    missing = []
    for chunk_id, chunk in zip(ids, chunks, strict=True):
        if chunk_id in existing and existing[chunk_id] != chunk.content_hash:
            raise ValueError("Stored embedding hash differs from immutable chunk")
        if chunk_id not in existing:
            missing.append((chunk_id, chunk))
    created_embeddings = 0
    for start in range(0, len(missing), embedding.batch_size):
        batch = missing[start : start + embedding.batch_size]
        vectors = embed_batch(
            client,
            [chunk.text for _, chunk in batch],
            model=embedding.model,
            dimensions=embedding.dimensions,
        )
        created_embeddings += persist_embeddings(
            engine, document_version_id, batch, vectors, client.provider, embedding
        )
    return IndexResult(
        document_version_id,
        created_chunks,
        len(chunks) - created_chunks,
        created_embeddings,
        len(chunks) - created_embeddings,
        embedding.model,
    )
