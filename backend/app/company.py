import argparse
import logging
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.schemas.company import CompanyInput
from app.services.companies import create_company, show_company

logger = logging.getLogger(__name__)
MAX_PROFILE_BYTES = 2_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import or inspect a company profile")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create").add_argument("--file", type=Path, required=True)
    commands.add_parser("show").add_argument("--company-id", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "show" and args.company_id <= 0:
        parser.error("--company-id must be positive")
    try:
        profile = None
        if args.command == "create":
            with args.file.open("rb") as source:
                data = source.read(MAX_PROFILE_BYTES + 1)
            if len(data) > MAX_PROFILE_BYTES:
                raise ValueError("Profile exceeds import limit")
            profile = CompanyInput.model_validate_json(data)
        engine = create_database_engine(Settings())
        try:
            if profile is not None:
                print(f"company_id={create_company(engine, profile)}")
            else:
                print(show_company(engine, args.company_id).model_dump_json(indent=2))
        finally:
            engine.dispose()
        return 0
    except (ValueError, OSError, SQLAlchemyError) as exc:
        logger.error("Company command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
