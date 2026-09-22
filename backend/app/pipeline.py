import argparse
import json
import logging

from app.core.config import Settings
from app.db.session import create_database_engine
from app.services.pipeline import SOURCES, mark_stale, recent_runs, run_status

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trigger and inspect background source pipelines"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--source", choices=SOURCES, required=True)
    status = commands.add_parser("status")
    status.add_argument("--run-id", type=int, required=True)
    status.add_argument("--after-stage-id", type=int, default=0)
    status.add_argument("--limit", type=int, default=100)
    recent = commands.add_parser("recent")
    recent.add_argument("--limit", type=int, default=20)
    commands.add_parser("mark-stale")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        engine = create_database_engine(settings)
        try:
            if args.command == "run":
                from app.worker.tasks import trigger_pipeline

                result = trigger_pipeline(engine, args.source)
            elif args.command == "status":
                result = run_status(
                    engine,
                    args.run_id,
                    after_stage_id=args.after_stage_id,
                    limit=args.limit,
                )
            elif args.command == "recent":
                result = recent_runs(engine, args.limit)
            else:
                result = {
                    "marked_stale": mark_stale(
                        engine, settings.pipeline_stale_after_minutes
                    )
                }
            print(json.dumps(result, sort_keys=True))
            return int(
                isinstance(result, dict)
                and result.get("status") in {"failed", "partial"}
            )
        finally:
            engine.dispose()
    except Exception:
        logger.error(
            "Pipeline command failed; check configuration, "
            "database and broker availability"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
