import argparse
import logging
from dataclasses import asdict

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.scrapers.contracts_finder import fetch_releases
from app.scrapers.contracts_finder_documents import discover_documents
from app.scrapers.errors import SourceFetchError, SourceParseError
from app.services.document_download import supported_pdf
from app.services.documents import process_documents

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Contracts Finder documents: ingest tenders first."
    )
    parser.add_argument(
        "--source", choices=["contracts-finder"], default="contracts-finder"
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Metadata only; no database or PDF downloads",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        with httpx.Client(trust_env=False) as client:
            listing = discover_documents(fetch_releases(client))
            if args.fetch_only:
                supported = sum(supported_pdf(record) for record in listing.records)
                print(
                    f"discovered={len(listing.records)} supported_pdfs={supported} "
                    f"unsupported_or_external={len(listing.records) - supported} "
                    f"failed={listing.failed} (metadata only)"
                )
                return 1 if listing.failed else 0
            logger.info(
                "Processing documents for existing tenders; ingest tenders first"
            )
            settings = Settings()
            engine = create_database_engine(settings)
            try:
                result = process_documents(engine, client, listing.records, settings)
            finally:
                engine.dispose()
            result.failed += listing.failed
            print(" ".join(f"{key}={value}" for key, value in asdict(result).items()))
            return 1 if result.failed else 0
    except (
        SourceFetchError,
        SourceParseError,
        ValidationError,
        SQLAlchemyError,
    ) as exc:
        logger.error("Document command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
