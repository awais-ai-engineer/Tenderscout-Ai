import argparse
import logging
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from app.ai.client import ProviderError
from app.ai.embeddings import OpenAIEmbeddingClient
from app.core.config import Settings
from app.db.session import create_database_engine
from app.rag.config import ChunkConfig, EmbeddingConfig
from app.services.indexing import index_document, prepare_index

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index one extracted document version")
    parser.add_argument("--document-version-id", type=int, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    if args.document_version_id <= 0:
        parser.error("--document-version-id must be positive")
    for name in ("openai", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        settings = Settings()
        chunking = ChunkConfig(
            size=settings.rag_chunk_size_chars, overlap=settings.rag_chunk_overlap_chars
        )
        if not args.prepare_only and (
            settings.openai_api_key is None or settings.ai_embedding_model is None
        ):
            logger.error(
                "OPENAI_API_KEY and AI_EMBEDDING_MODEL are required for indexing"
            )
            return 1
        engine = create_database_engine(settings)
        try:
            if args.prepare_only:
                chunks = prepare_index(engine, args.document_version_id, chunking)
                lengths = [len(chunk.text) for chunk in chunks]
                average = sum(lengths) / len(lengths) if lengths else 0
                print(
                    f"document_version_id={args.document_version_id} "
                    f"chunk_count={len(chunks)} "
                    f"min_chars={min(lengths, default=0)} "
                    f"max_chars={max(lengths, default=0)} "
                    f"average_chars={average:.1f} persisted=false"
                )
                return 0
            client = OpenAIEmbeddingClient(settings.openai_api_key)
            try:
                result = index_document(
                    engine,
                    args.document_version_id,
                    client,
                    chunking=chunking,
                    embedding=EmbeddingConfig(
                        model=settings.ai_embedding_model,
                        dimensions=settings.ai_embedding_dimensions,
                        batch_size=settings.rag_embedding_batch_size,
                    ),
                )
            finally:
                client.close()
            print(" ".join(f"{key}={value}" for key, value in asdict(result).items()))
            return 0
        finally:
            engine.dispose()
    except (ValueError, ProviderError, SQLAlchemyError) as exc:
        logger.error("Index command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
