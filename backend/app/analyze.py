import argparse
import logging

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.ai.openai_client import OpenAIStructuredClient
from app.core.config import Settings
from app.db.session import create_database_engine
from app.services.analysis import (
    DocumentVersionNotFound,
    analyze_document,
    prepare_document,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze one extracted document version"
    )
    parser.add_argument("--document-version-id", type=int, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    if args.document_version_id <= 0:
        parser.error("--document-version-id must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for name in ("openai", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        settings = Settings()
        if not args.prepare_only and (
            settings.ai_model is None or settings.openai_api_key is None
        ):
            logger.error("AI_MODEL and OPENAI_API_KEY are required for analysis")
            return 1
        engine = create_database_engine(settings)
        try:
            if args.prepare_only:
                prepared = prepare_document(
                    engine, args.document_version_id, settings.ai_max_input_chars
                )
                if prepared is None:
                    print(
                        f"document_version_id={args.document_version_id} "
                        "status=skipped (no extracted text)"
                    )
                else:
                    print(
                        f"document_version_id={args.document_version_id} "
                        f"status=prepared input_chars={len(prepared.text)} "
                        f"input_hash={prepared.input_hash} "
                        f"truncated={str(prepared.truncated).lower()} persisted=false"
                    )
                return 0
            client = OpenAIStructuredClient(settings.openai_api_key)
            try:
                result = analyze_document(
                    engine,
                    args.document_version_id,
                    client,
                    model=settings.ai_model,
                    max_input_chars=settings.ai_max_input_chars,
                )
            finally:
                client.close()
            print(
                f"document_version_id={result.document_version_id} "
                f"status={result.status} "
                f"analysis_id={result.analysis_id} model={result.model} "
                f"reused={str(result.reused).lower()}"
            )
            return 1 if result.status == "failed" else 0
        finally:
            engine.dispose()
    except DocumentVersionNotFound:
        logger.error("Document version does not exist")
        return 1
    except (ValidationError, SQLAlchemyError) as exc:
        logger.error("Analysis command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
