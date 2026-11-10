"""Optional inputs for the dashboard: money put into an account and premiums already paid."""

import sqlalchemy as sa
from alembic import op

revision = "0028_dashboard_inputs"
down_revision = "0027_expense_import"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "financial_accounts", sa.Column("contributed_krw", sa.Numeric(20, 0), nullable=True)
    )
    op.add_column("financial_accounts", sa.Column("contributed_as_of", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_financial_accounts_contribution"),
        "financial_accounts",
        "(contributed_krw IS NULL AND contributed_as_of IS NULL) "
        "OR (contributed_krw IS NOT NULL AND contributed_krw >= 0)",
    )
    op.add_column(
        "insurance_policies", sa.Column("premium_paid_before_krw", sa.Numeric(20, 0), nullable=True)
    )
    op.add_column("insurance_policies", sa.Column("premium_paid_through", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_insurance_policies_premium_paid_before"),
        "insurance_policies",
        "(premium_paid_before_krw IS NULL) = (premium_paid_through IS NULL) "
        "AND (premium_paid_before_krw IS NULL OR premium_paid_before_krw >= 0)",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_insurance_policies_premium_paid_before"), "insurance_policies", type_="check"
    )
    op.drop_column("insurance_policies", "premium_paid_through")
    op.drop_column("insurance_policies", "premium_paid_before_krw")
    op.drop_constraint(
        op.f("ck_financial_accounts_contribution"), "financial_accounts", type_="check"
    )
    op.drop_column("financial_accounts", "contributed_as_of")
    op.drop_column("financial_accounts", "contributed_krw")
