import argparse
import logging

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.scrapers.errors import SourceFetchError, SourceParseError
from app.services.ingestion import InactiveSourceError, ingest_tenders
from app.sources import SOURCE_CONNECTORS, connector

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest one public procurement listing or API batch"
    )
    parser.add_argument(
        "--source",
        choices=tuple(SOURCE_CONNECTORS),
        default="find-a-tender",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch and validate without database writes",
    )
    args = parser.parse_args()
    source = connector(args.source)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        settings = None if args.fetch_only else Settings()
        with httpx.Client(follow_redirects=False) as client:
            listing = source.refresh(client, limit=100, timeout=30.0)
        if args.fetch_only:
            print(
                f"source: {source.slug}\nmode: fetch-only (no database writes)\n"
                f"discovered: {listing.discovered}\nvalid: {len(listing.records)}\n"
                f"failed: {listing.failed}\nskipped: {listing.skipped}"
            )
            return 1 if listing.failed else 0
        assert settings is not None
        engine = create_database_engine(settings)
        try:
            result = ingest_tenders(engine, source.source, listing)
        finally:
            engine.dispose()
    except (SourceFetchError, SourceParseError, InactiveSourceError) as error:
        logger.error("event=run_failed source=%s reason=%s", source.slug, error)
        return 1
    except (SQLAlchemyError, ValidationError) as error:
        logger.error(
            "event=run_failed source=%s error=%s "
            "check_configuration_and_migrations=true",
            source.slug,
            type(error).__name__,
        )
        return 1
    print(
        f"source: {source.slug}\ndiscovered: {result.discovered}\n"
        f"created: {result.created}\nchanged: {result.changed}\n"
        f"unchanged: {result.unchanged}\n"
        f"failed: {result.failed}\nskipped: {result.skipped}"
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
