"""Add saved tenders, notification preferences, and durable alerts."""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_tenders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_saved_tenders"),
        sa.UniqueConstraint("company_id", "tender_id", name="uq_saved_company_tender"),
    )
    op.create_index("ix_saved_tenders_company_id", "saved_tenders", ["company_id"])
    op.create_table(
        "notification_preferences",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column(
            "email_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("notification_email", sa.String(length=320), nullable=True),
        sa.Column(
            "minimum_match_score", sa.Integer(), server_default="70", nullable=False
        ),
        sa.Column(
            "new_match_alerts", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "tender_change_alerts",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "deadline_reminders", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "delivery_mode",
            sa.String(length=16),
            server_default="instant",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "minimum_match_score >= 0 AND minimum_match_score <= 100",
            name="ck_notification_threshold",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('instant', 'daily_digest')",
            name="ck_notification_delivery_mode",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("company_id", name="pk_notification_preferences"),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "delivery_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('new_match', 'tender_updated', 'deadline_reminder')",
            name="ck_alert_type",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'unconfigured', 'sent', 'failed')",
            name="ck_alert_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["match_id"], ["tender_matches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.UniqueConstraint("dedupe_key", name="uq_alerts_dedupe_key"),
    )
    op.create_index("ix_alerts_company_created", "alerts", ["company_id", "created_at"])
    op.execute(
        "INSERT INTO notification_preferences (company_id) "
        "SELECT id FROM company_profiles"
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("notification_preferences")
    op.drop_table("saved_tenders")
