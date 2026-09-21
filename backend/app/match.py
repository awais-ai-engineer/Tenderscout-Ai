import argparse
import logging
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.services.matching import match_tender

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Match a company to a completed analysis"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--analysis-id", type=int, required=True)
    args = parser.parse_args(argv)
    if args.company_id <= 0 or args.analysis_id <= 0:
        parser.error("Identifiers must be positive")
    try:
        engine = create_database_engine(Settings())
        try:
            result = match_tender(engine, args.company_id, args.analysis_id)
            print(
                " ".join(
                    f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                    for key, value in asdict(result).items()
                )
            )
            return 0
        finally:
            engine.dispose()
    except (ValueError, SQLAlchemyError) as exc:
        logger.error("Match command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
