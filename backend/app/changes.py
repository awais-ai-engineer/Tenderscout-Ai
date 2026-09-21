import argparse
import json
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_database_engine
from app.services.change_detection import (
    ComparisonError,
    compare_document,
    compare_metadata,
)
from app.services.change_rules import canonical_datetime
from app.services.revisions import revision_history

logger = logging.getLogger(__name__)
MAX_PRINTED_CHANGES = 25
MAX_PREVIEW_CHARS = 320


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect recorded tender revision changes"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    history = commands.add_parser("history")
    history.add_argument("--tender-id", type=int, required=True)
    history.add_argument("--after-index", type=int, default=0)
    history.add_argument("--limit", type=int, default=100)
    metadata = commands.add_parser("metadata")
    metadata.add_argument("--from-revision-id", type=int, required=True)
    metadata.add_argument("--to-revision-id", type=int, required=True)
    document = commands.add_parser("document")
    document.add_argument("--from-analysis-id", type=int, required=True)
    document.add_argument("--to-analysis-id", type=int, required=True)
    args = parser.parse_args(argv)
    if any(value <= 0 for name, value in vars(args).items() if name.endswith("_id")):
        parser.error("Identifiers must be positive")
    try:
        engine = create_database_engine(Settings())
        try:
            if args.command == "history":
                rows = revision_history(
                    engine,
                    args.tender_id,
                    after_index=args.after_index,
                    limit=args.limit,
                )
                for row in rows:
                    deadline = (
                        canonical_datetime(row["deadline"]) if row["deadline"] else None
                    )
                    print(
                        f"revision_id={row['id']} "
                        f"revision_index={row['revision_index']} "
                        f"observed_at={canonical_datetime(row['observed_at'])} "
                        f"deadline={deadline} "
                        f"snapshot_hash={row['snapshot_hash'][:12]}"
                    )
                if len(rows) == args.limit:
                    print(f"next_after_index={rows[-1]['revision_index']}")
                if not rows:
                    print("No recorded revisions in this range.")
                return 0
            metadata_mode = args.command == "metadata"
            result = (
                compare_metadata(engine, args.from_revision_id, args.to_revision_id)
                if metadata_mode
                else compare_document(
                    engine, args.from_analysis_id, args.to_analysis_id
                )
            )
            parent = "tender_id" if metadata_mode else "document_id"
            identity = "revision_id" if metadata_mode else "analysis_id"
            print(
                f"change_set_id={result.change_set_id} {parent}={result.parent_id} "
                f"from_{identity}={result.from_id} to_{identity}={result.to_id} "
                f"changes={result.change_count} reused={str(result.reused).lower()}"
            )
            for change in result.changes[:MAX_PRINTED_CHANGES]:
                print(
                    f"{change.get('field', change.get('category'))} "
                    f"{change['change_type']}:"
                )
                for side in ("old", "new"):
                    value = change.get(side, change.get(side + "_preview"))
                    encoded = json.dumps(value, ensure_ascii=True)
                    print(
                        f"  {side}={encoded[:MAX_PREVIEW_CHARS]}"
                        + ("..." if len(encoded) > MAX_PREVIEW_CHARS else "")
                    )
                if change.get("requires_review"):
                    print(f"  match_basis={change['match_basis']} requires_review=true")
            if result.change_count > MAX_PRINTED_CHANGES:
                print(f"omitted_changes={result.change_count - MAX_PRINTED_CHANGES}")
            return 0
        finally:
            engine.dispose()
    except ComparisonError as exc:
        logger.error("Comparison rejected: %s", exc)
        return 1
    except (ValueError, SQLAlchemyError) as exc:
        logger.error("Changes command failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
