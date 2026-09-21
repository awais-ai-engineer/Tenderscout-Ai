import argparse
import logging
from contextlib import ExitStack

from sqlalchemy.exc import SQLAlchemyError

from app.ai.client import ProviderError
from app.ai.embeddings import OpenAIEmbeddingClient
from app.ai.openai_client import OpenAIStructuredClient
from app.core.config import Settings
from app.db.session import create_database_engine
from app.rag.config import EmbeddingConfig
from app.rag.schemas import TenderAnswerOutput
from app.services.qa import INSUFFICIENT_MESSAGE, ask_tender
from app.services.retrieval import normalize_question, retrieve

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask one indexed tender document version"
    )
    parser.add_argument("--document-version-id", type=int, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--retrieve-only", action="store_true")
    args = parser.parse_args(argv)
    if args.document_version_id <= 0:
        parser.error("--document-version-id must be positive")
    for name in ("openai", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        question = normalize_question(args.question)
        settings = Settings()
        if settings.openai_api_key is None or settings.ai_embedding_model is None:
            logger.error(
                "OPENAI_API_KEY and AI_EMBEDDING_MODEL are required for retrieval"
            )
            return 1
        if not args.retrieve_only and settings.ai_model is None:
            logger.error("AI_MODEL is required for answering")
            return 1
        config = EmbeddingConfig(
            model=settings.ai_embedding_model,
            dimensions=settings.ai_embedding_dimensions,
            batch_size=settings.rag_embedding_batch_size,
        )
        with ExitStack() as stack:
            engine = create_database_engine(settings)
            stack.callback(engine.dispose)
            embedding_client = OpenAIEmbeddingClient(settings.openai_api_key)
            stack.callback(embedding_client.close)
            if args.retrieve_only:
                chunks = retrieve(
                    engine,
                    args.document_version_id,
                    question,
                    embedding_client,
                    embedding=config,
                    top_k=settings.rag_top_k,
                )
                for rank, chunk in enumerate(chunks, 1):
                    preview = " ".join(chunk.text.split())[:160]
                    print(
                        f"rank={rank} chunk_id={chunk.chunk_id} "
                        f"document_version_id={chunk.document_version_id} "
                        f"chunk_index={chunk.chunk_index} preview={preview!r}"
                    )
                return 0
            answer_client = OpenAIStructuredClient(
                settings.openai_api_key, output_schema=TenderAnswerOutput
            )
            stack.callback(answer_client.close)
            result = ask_tender(
                engine,
                args.document_version_id,
                question,
                embedding_client,
                answer_client,
                embedding=config,
                answer_model=settings.ai_model,
                top_k=settings.rag_top_k,
                max_context_chars=settings.rag_max_context_chars,
            )
            if result.status == "completed":
                print(f"answer:\n{result.answer}\ncitations:")
                for citation in result.citations:
                    print(
                        f"- document_version_id={citation['document_version_id']} "
                        f"chunk_id={citation['chunk_id']} "
                        f"chunk_index={citation['chunk_index']}: "
                        f"{citation['quote']!r}"
                    )
            elif result.status == "insufficient":
                print(INSUFFICIENT_MESSAGE)
            else:
                print(f"Answer failed: {result.failure_reason}")
            print(
                f"question_id={result.question_id} status={result.status} "
                f"reused={str(result.reused).lower()}"
            )
            return 1 if result.status == "failed" else 0
    except (ValueError, ProviderError, SQLAlchemyError) as exc:
        logger.error("Ask command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
