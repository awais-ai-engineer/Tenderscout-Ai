"""Allow TED source refresh runs."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_pipeline_source", "pipeline_runs", type_="check")
    op.create_check_constraint(
        "ck_pipeline_source",
        "pipeline_runs",
        "source_slug IN ('find-a-tender', 'contracts-finder', 'ted')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pipeline_source", "pipeline_runs", type_="check")
    op.create_check_constraint(
        "ck_pipeline_source",
        "pipeline_runs",
        "source_slug IN ('find-a-tender', 'contracts-finder')",
    )
