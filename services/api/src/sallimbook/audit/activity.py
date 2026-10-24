"""Current, household-scoped names for existing audit events; never store name snapshots."""

from collections import defaultdict

from sqlalchemy import and_, func, select

from sallimbook.audit.schemas import ActivityEventResponse, ActivityListResponse
from sallimbook.core.database import Base

# Explicit public label columns. Never load whole entities, medical prose, numbers or secrets.
# (root table, parent joins (local foreign key, table), name column, path template)
TARGETS = {
    "asset": ("assets", (), "name", "/assets/{id}"),
    "financial_account": (
        "financial_accounts",
        (("asset_id", "assets"),),
        "name",
        "/accounts/{id}",
    ),
    "card": ("cards", (), "alias", "/cards/{id}"),
    "insurance_policy": ("insurance_policies", (), "product_name", "/insurance/policies/{id}"),
    "insurance_coverage": (
        "insurance_coverages",
        (("policy_id", "insurance_policies"),),
        "product_name",
        "/insurance/policies/{parent_id}",
    ),
    "policy_premium_link": (
        "policy_premium_links",
        (("policy_id", "insurance_policies"),),
        "product_name",
        "/insurance/policies/{parent_id}",
    ),
    "insurance_case": ("insurance_cases", (), "title", "/insurance/cases/{id}"),
    "medical_node": (
        "medical_nodes",
        (("case_id", "insurance_cases"),),
        "title",
        "/insurance/cases/{parent_id}/nodes/{id}",
    ),
    "medical_expense": (
        "medical_expenses",
        (("case_id", "insurance_cases"),),
        "title",
        "/insurance/expenses/{id}",
    ),
    "medical_refund": (
        "medical_refunds",
        (("expense_id", "medical_expenses"), ("case_id", "insurance_cases")),
        "title",
        "/insurance/refunds/{id}",
    ),
    "insurance_claim": (
        "insurance_claims",
        (("case_id", "insurance_cases"),),
        "title",
        "/insurance/claims/{id}",
    ),
    "insurance_payout": (
        "insurance_payouts",
        (("cash_record_id", "cash_records"),),
        "period_month",
        "/insurance/payouts/{id}",
    ),
    "insurance_return": (
        "insurance_returns",
        (("cash_record_id", "cash_records"),),
        "period_month",
        "/insurance/returns/{id}",
    ),
    "payout_allocation": (
        "payout_allocations",
        (("case_id", "insurance_cases"),),
        "title",
        "/insurance/payouts/{link_id}",
    ),
    "appliance": ("appliances", (), "name", "/appliances/{id}"),
    "consumable": ("consumables", (), "name", "/consumables/{id}"),
    "appliance_consumable": (
        "appliance_consumables",
        (("consumable_id", "consumables"),),
        "name",
        "/appliance-consumables/{id}",
    ),
    "stock_movement": (
        "stock_movements",
        (("consumable_id", "consumables"),),
        "name",
        "/consumables/{parent_id}/stock/{id}",
    ),
    "consumable_replacement": (
        "consumable_replacements",
        (("consumable_id", "consumables"),),
        "name",
        "/appliance-consumables/{link_id}/replacements/{id}",
    ),
    "obligation": ("scheduled_obligations", (), "title", "/fixed-payments/{id}"),
    "fixed_settlement": (
        "fixed_settlements",
        (("obligation_id", "scheduled_obligations"),),
        "title",
        "/fixed-payments/{parent_id}",
    ),
    "asset_month": (
        "asset_month_revisions",
        (("month_id", "asset_months"),),
        "period_month",
        "/assets/months/{month}?revision={revision}",
    ),
    "recurring_rule": ("recurring_rules", (), None, "/fixed-payments/rules/{id}"),
    "cash_record": ("cash_records", (), "period_month", None),
    "income_conversion": ("income_conversions", (), None, "/income"),
    "household_person": ("household_people", (), "display_name", "/settings/people"),
}
BUSINESS_TYPES = frozenset(TARGETS)


def project_activity(session, household_id, items, next_cursor):
    groups = defaultdict(list)
    for item in items:
        groups[item.entity_type].append(item.entity_id)
    targets = {}
    tables = Base.metadata.tables
    for kind, identifiers in groups.items():
        table_name, joins, name, path = TARGETS[kind]
        root = tables[table_name]
        current = root
        source = root
        for foreign_key, parent_name in joins:
            parent = tables[parent_name]
            source = source.join(
                parent,
                and_(
                    current.c[foreign_key] == parent.c.id,
                    current.c.household_id == parent.c.household_id,
                ),
            )
            current = parent
        columns = [root.c.id, current.c.id.label("parent_id")]
        if kind in ("consumable_replacement", "payout_allocation"):
            columns.append(
                root.c[
                    "appliance_consumable_id" if kind == "consumable_replacement" else "payout_id"
                ].label("link_id")
            )
        if name:
            label_column = (
                func.coalesce(root.c.alias, root.c.product_name)
                if kind == "card"
                else current.c[name]
            )
            columns.append(label_column.label("name"))
        if kind == "asset_month":
            columns.append(root.c.revision_no)
        if kind == "cash_record":
            columns.append(root.c.kind)
        if kind == "recurring_rule":
            versions = tables["recurring_rule_versions"]
            title = (
                select(versions.c.title)
                .where(
                    versions.c.household_id == root.c.household_id,
                    versions.c.rule_id == root.c.id,
                    versions.c.revoked_at.is_(None),
                )
                .order_by(
                    versions.c.effective_from.desc(),
                    versions.c.created_at.desc(),
                    versions.c.id.desc(),
                )
                .limit(1)
                .scalar_subquery()
            )
            columns.append(title.label("name"))
        rows = session.execute(
            select(*columns)
            .select_from(source)
            .where(root.c.household_id == household_id, root.c.id.in_(identifiers))
        ).mappings()
        for row in rows:
            label = str(
                row.get("name")
                or {
                    "payout_allocation": "보험금 배분",
                    "consumable_replacement": "소모품 교체",
                    "recurring_rule": "고정 납부 규칙",
                    "income_conversion": "수입 입력 방식",
                }.get(kind, "이름 미입력")
            )
            label = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in label)
            route = path
            if kind == "cash_record" and row["kind"] in (
                "salary",
                "bonus",
                "other_income",
                "income_return",
            ):
                route = "/income/{id}"
            target_path = (
                route.format(
                    id=row["id"],
                    parent_id=row["parent_id"],
                    link_id=row.get("link_id"),
                    month=label[:7],
                    revision=row.get("revision_no"),
                )
                if route
                else None
            )
            targets[(kind, row["id"])] = (label, target_path)
    output = []
    for item in items:
        name, path = targets.get((item.entity_type, item.entity_id), (None, None))
        output.append(
            ActivityEventResponse(**item.model_dump(), target_name=name, target_path=path)
        )
    return ActivityListResponse(items=output, next_cursor=next_cursor)
