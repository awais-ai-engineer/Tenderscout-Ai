"""Add company profiles and append-only deterministic matches."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("annual_revenue", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("years_in_business", sa.Integer(), nullable=True),
        sa.Column(
            "capabilities_complete",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "certifications_complete",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "experience_complete",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "financials_complete",
            sa.Boolean(),
            server_default=sa.false(),
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
        sa.CheckConstraint("annual_revenue >= 0", name="ck_company_annual_revenue"),
        sa.CheckConstraint("employee_count >= 0", name="ck_company_employee_count"),
        sa.CheckConstraint("years_in_business >= 0", name="ck_company_years"),
        sa.PrimaryKeyConstraint("id", name="pk_company_profiles"),
    )
    op.create_table(
        "company_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_key", sa.String(length=765), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company_profiles.id"],
            name="fk_company_capabilities_company_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_capabilities"),
        sa.UniqueConstraint(
            "company_id", "name_key", name="uq_capabilities_company_name"
        ),
    )
    op.create_index(
        op.f("ix_company_capabilities_company_id"),
        "company_capabilities",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "company_certifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("identifier", sa.String(length=255), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("valid_until >= valid_from", name="ck_certification_dates"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company_profiles.id"],
            name="fk_company_certifications_company_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_certifications"),
    )
    op.create_index(
        op.f("ix_company_certifications_company_id"),
        "company_certifications",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "company_experience",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("client", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=255), nullable=True),
        sa.Column("contract_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("completed_at >= started_at", name="ck_experience_dates"),
        sa.CheckConstraint("contract_value >= 0", name="ck_experience_value"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company_profiles.id"],
            name="fk_company_experience_company_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_experience"),
    )
    op.create_index(
        op.f("ix_company_experience_company_id"),
        "company_experience",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "tender_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tender_analysis_id", sa.Integer(), nullable=False),
        sa.Column("matcher_version", sa.String(length=32), nullable=False),
        sa.Column("eligibility_status", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("coverage_ratio", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column(
            "company_snapshot",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "hard_blockers",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "matched_requirements",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "unmatched_requirements",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "unknown_requirements",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "capability_matches",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "certification_matches",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "experience_matches",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "risks",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "eligibility_status IN ('eligible', 'ineligible', 'uncertain')",
            name="ck_matches_status",
        ),
        sa.CheckConstraint(
            "coverage_ratio >= 0 AND coverage_ratio <= 1", name="ck_matches_coverage"
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_matches_score"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company_profiles.id"],
            name="fk_matches_company_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tender_analysis_id"],
            ["tender_analyses.id"],
            name="fk_matches_analysis_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tender_matches"),
        sa.UniqueConstraint(
            "company_id",
            "tender_analysis_id",
            "matcher_version",
            name="uq_matches_identity",
        ),
    )
    op.create_index(
        op.f("ix_tender_matches_tender_analysis_id"),
        "tender_matches",
        ["tender_analysis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tender_matches")
    op.drop_table("company_experience")
    op.drop_table("company_certifications")
    op.drop_table("company_capabilities")
    op.drop_table("company_profiles")
