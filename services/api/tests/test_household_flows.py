"""Month-by-month household figures, money put into investment accounts, premiums vs benefits."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_accounts import asset_payload, create_account
from test_asset_months import draft, observe
from test_expense_plans import change as change_plan
from test_expense_plans import create as create_plan
from test_household_overview import env, overview, register_assets  # noqa: F401
from test_income import headers
from test_insurance_core import case_payload, policy_payload
from test_insurance_events import actual, allocation, money

pytestmark = pytest.mark.database


def test_percent_rounds_half_up_and_never_shows_a_negative_zero():
    from sallimbook.overview.service import percent

    assert percent(1490000, 10000000) == "14.9"
    assert percent(-1000000, 6000000) == "-16.7"
    assert percent(5, 10000) == "0.1"
    assert percent(-1, 10000000) == "0.0"
    assert percent(0, 5) == "0.0"
    assert percent(1, 0) is None


def trends(client, actor, to="2026-03", months=3, status=200):
    response = client.get(
        "/api/v1/household-trends", params={"to": to, "months": months}, headers=actor.headers
    )
    assert response.status_code == status, response.text
    if status == 200:
        assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_net_assets_by_month_use_the_latest_amount_saved_up_to_each_month(env):  # noqa: F811
    app, actor, foreign = env
    with TestClient(app) as client:
        register_assets(client, actor)
        result = trends(client, actor)
        long = trends(client, actor, months=12)
        theirs = trends(client, foreign)
        assert trends(client, actor, to="2026-04", status=422)["error"]["code"] == (
            "INVALID_MONTH_RANGE"
        )
        assert client.get("/api/v1/household-trends", params={"to": "2026-03"}).status_code == 401
        latest = overview(client, actor)["holdings"]
    assert [point["month"] for point in result["net_assets"]] == ["2026-01", "2026-02", "2026-03"]
    january, february, march = result["net_assets"]
    # January: the account, the older stock and home amounts, and the deposit that ended later.
    assert january["assets_krw"] == "301500777" and january["liabilities_krw"] == "0"
    assert january["net_assets_krw"] == "301500777" and january["entered_count"] == 2
    # February: the loan's first amount arrives and the ended deposit is no longer held.
    assert february["assets_krw"] == "301500000" and february["liabilities_krw"] == "100000000"
    assert february["net_assets_krw"] == "201500000" and february["entered_count"] == 1
    # The last month equals the home status for that month.
    assert march["net_assets_krw"] == latest["net_assets_krw"] == "201700000"
    assert march["known_count"] == latest["known_count"]
    assert not any(point["confirmed"] for point in result["net_assets"])
    # A month before anything was saved has no total, not a zero.
    early = long["net_assets"][0]
    assert early["month"] == "2025-04" and early["net_assets_krw"] is None
    assert early["known_count"] == 0 and early["item_count"] > 0
    assert all(point["net_assets_krw"] is None for point in theirs["net_assets"])


def test_plan_margin_by_month_follows_the_plan_and_income_registered_then(env):  # noqa: F811
    app, actor, _ = env
    with TestClient(app) as client:
        create_plan(client, actor, expected_amount_krw="1000000", effective_from="2026-01-01")
        create_plan(
            client,
            actor,
            title="합성 대출 상환",
            economic_type="loan",
            expected_amount_krw="400000",
            effective_from="2026-02-01",
        )
        create_plan(
            client,
            actor,
            title="합성 연금 납입",
            economic_type="asset_transfer",
            expected_amount_krw="300000",
            effective_from="2026-03-01",
        )
        income = client.post(
            "/api/v1/income-planning/expected",
            headers=headers(actor),
            json={"member_id": str(actor.member_id), "label": "합성 급여", "amount_krw": "3000000"},
        )
        assert income.status_code == 201, income.text
        # The first amount was registered in January; the raise below is saved "now" (March).
        with app.state.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE income_planning_revisions SET created_at = :at "
                    "WHERE resource_id = :id AND version = 1"
                ),
                {"at": datetime(2026, 1, 10, tzinfo=UTC), "id": income.json()["id"]},
            )
        raised = client.put(
            f"/api/v1/income-planning/expected/{income.json()['id']}",
            headers=headers(actor, version=1),
            json={
                "member_id": str(actor.member_id),
                "label": "합성 급여",
                "amount_krw": "3500000",
                "reason": "합성 급여 인상",
            },
        )
        assert raised.status_code == 200, raised.text
        result = trends(client, actor, months=4)["plan"]
        current = overview(client, actor)["plan"]
    december, january, february, march = result
    # Nothing was registered in December: no income, so no margin rather than a deficit.
    assert december["income_count"] == 0 and december["margin_after_transfers_krw"] is None
    assert december["spending_known_krw"] == "0"
    assert january["as_of"] == "2026-01-31" and january["income_known_krw"] == "3000000"
    assert january["spending_known_krw"] == "1000000" and january["loan_known_krw"] == "0"
    assert january["margin_before_transfers_krw"] == "2000000"
    assert february["loan_known_krw"] == "400000"
    assert february["margin_after_transfers_krw"] == "1600000"
    # The running month is read as of today and matches the home's plan margin.
    assert march["as_of"] == "2026-03-15" and march["income_known_krw"] == "3500000"
    assert march["transfer_known_krw"] == "300000"
    assert march["margin_before_transfers_krw"] == current["margin_before_transfers_krw"]
    assert (
        march["margin_after_transfers_krw"] == current["margin_after_transfers_krw"] == ("1800000")
    )
    assert all(point["actual_income_krw"] == "0" for point in result)


def test_investment_accounts_compare_latest_value_with_money_put_in(env):  # noqa: F811
    app, actor, foreign = env
    with TestClient(app) as client:
        stock = create_account(
            client,
            actor,
            asset=asset_payload(name="합성 증권 계좌"),
            account_type="brokerage",
            account_number=None,
            contributed_krw="10000000",
            contributed_as_of="2026-02-28",
        )
        pension = create_account(
            client,
            actor,
            asset=asset_payload(name="합성 연금저축"),
            account_type="pension_savings",
            account_number=None,
        )
        checking = create_account(
            client,
            actor,
            asset=asset_payload(name="합성 입출금"),
            account_number=None,
            contributed_krw="1",
        )
        assert stock["contributed_krw"] == "10000000" and pension["contributed_krw"] is None
        draft(client, actor, "2026-03", copy=False)
        observe(client, actor, "2026-03", stock["asset"]["id"], "11490000", "2026-03-14")
        observe(client, actor, "2026-03", pension["asset"]["id"], "5000000", "2026-03-14")
        observe(client, actor, "2026-03", checking["asset"]["id"], "700", "2026-03-14")
        first = overview(client, actor)["investments"]
        # A date without an amount is refused; clearing the amount clears its date.
        refused = client.patch(
            f"/api/v1/accounts/{pension['id']}",
            headers={**actor.headers, "If-Match": '"1"'},
            json={"contributed_as_of": "2026-03-01"},
        )
        assert refused.status_code == 422, refused.text
        patched = client.patch(
            f"/api/v1/accounts/{pension['id']}",
            headers={**actor.headers, "If-Match": '"1"'},
            json={"contributed_krw": "6000000", "contributed_as_of": "2026-03-01"},
        )
        assert patched.status_code == 200, patched.text
        second = overview(client, actor)["investments"]
        cleared = client.patch(
            f"/api/v1/accounts/{stock['id']}",
            headers={**actor.headers, "If-Match": '"1"'},
            json={"contributed_krw": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["contributed_as_of"] is None
        theirs = overview(client, foreign)["investments"]
    # A checking account is not an investment even when an amount was entered for it.
    assert first["count"] == 1 and first["missing_contribution_count"] == 1
    assert first["value_krw"] == "11490000" and first["contributed_krw"] == "10000000"
    assert first["gain_krw"] == "1490000" and first["return_percent"] == "14.9"
    assert first["items"][0]["account_id"] == stock["id"]
    assert first["items"][0]["contributed_as_of"] == "2026-02-28"
    assert second["count"] == 2 and second["missing_contribution_count"] == 0
    assert second["value_krw"] == "16490000" and second["contributed_krw"] == "16000000"
    assert second["gain_krw"] == "490000" and second["return_percent"] == "3.1"
    loss = {row["account_id"]: row for row in second["items"]}[pension["id"]]
    assert loss["gain_krw"] == "-1000000" and loss["return_percent"] == "-16.7"
    assert theirs["count"] == 0 and theirs["items"] == []


def test_premiums_paid_and_benefits_received_per_policy(env):  # noqa: F811
    app, actor, foreign = env
    base = "/api/v1/insurance"
    with TestClient(app) as client:

        def create(path, body, who=actor):
            response = client.post(base + path, headers=who.headers, json=body)
            assert response.status_code == 201, response.text
            return response.json()

        # Half of the entry is refused: the amount and its date belong together.
        assert (
            client.post(
                base + "/policies",
                headers=actor.headers,
                json=policy_payload(premium_paid_before_krw="1000000"),
            ).status_code
            == 422
        )
        covered = create(
            "/policies",
            policy_payload(
                product_name="합성 실손",
                premium_paid_before_krw="1000000",
                premium_paid_through="2025-12-31",
            ),
        )
        assert covered["premium_paid_before_krw"] == "1000000"
        bare = create("/policies", policy_payload(product_name="합성 미입력"))
        plan = create_plan(
            client,
            actor,
            title="합성 실손 보험료",
            category="보험료",
            expected_amount_krw="100000",
            effective_from="2026-01-01",
        )
        create(f"/policies/{covered['id']}/premium-links", {"rule_id": plan["id"]})
        case = create("/cases", case_payload(actor))
        reference = money(
            client,
            actor,
            "/payouts",
            actual(
                "500000",
                allocations=[
                    allocation(case["id"], "400000", policy_id=covered["id"]),
                    allocation(case["id"], "100000"),
                ],
            ),
        )
        payout = client.get(f"{base}/payouts/{reference['id']}", headers=actor.headers).json()
        tied = next(row for row in payout["allocations"] if row["policy_id"] == covered["id"])
        money(
            client,
            actor,
            f"/payouts/{payout['id']}/returns",
            actual("50000", original_allocation_id=tied["id"], reason="합성 보험사 반환"),
            version=payout["version"],
        )
        create("/policies", policy_payload(), foreign)
        response = client.get(base + "/summary", headers=actor.headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        theirs = client.get(base + "/summary", headers=foreign.headers).json()
        assert client.get(base + "/summary").status_code == 401
    assert result["as_of"] == "2026-03-15" and result["policy_count"] == 2
    rows = {row["policy_id"]: row for row in result["policies"]}
    row = rows[covered["id"]]
    # January to March at 100,000 a month on top of what was entered as already paid.
    assert row["paid_before_krw"] == "1000000" and row["paid_through"] == "2025-12-31"
    assert row["paid_estimated_krw"] == "300000" and row["estimated_months"] == 3
    assert row["estimated_from_month"] == "2026-01" and row["unknown_months"] == 0
    assert row["paid_total_krw"] == "1300000" and row["monthly_premium_krw"] == "100000"
    assert row["received_krw"] == "350000" and row["recovery_percent"] == "26.9"
    empty = rows[bare["id"]]
    assert empty["paid_total_krw"] is None and empty["recovery_percent"] is None
    assert empty["received_krw"] == "0" and empty["monthly_premium_krw"] == "0"
    assert result["paid_unknown_count"] == 1 and result["monthly_premium_krw"] == "100000"
    assert result["paid_total_krw"] == "1300000"
    # The part of the payout not tied to a policy still counts for the household.
    assert result["unassigned_received_krw"] == "100000" and result["received_krw"] == "450000"
    # The ratio only compares policies whose premiums are known with their own benefits.
    assert result["matched_received_krw"] == "350000" and result["recovery_percent"] == "26.9"
    assert theirs["policy_count"] == 1 and theirs["received_krw"] == "0"
    assert theirs["paid_total_krw"] == "0" and theirs["recovery_percent"] is None


def test_premium_estimate_stops_with_the_policy_and_counts_a_changed_month_once(env):  # noqa: F811
    app, actor, _ = env
    base = "/api/v1/insurance"
    with TestClient(app) as client:

        def create(path, body):
            response = client.post(base + path, headers=actor.headers, json=body)
            assert response.status_code == 201, response.text
            return response.json()

        def summary():
            response = client.get(base + "/summary", headers=actor.headers)
            assert response.status_code == 200, response.text
            return response.json()

        changed = create("/policies", policy_payload(product_name="합성 인상"))
        ended = create("/policies", policy_payload(product_name="합성 해지"))
        unpaid = create("/policies", policy_payload(product_name="합성 납입 미상"))
        rising = create_plan(
            client,
            actor,
            title="합성 인상 보험료",
            expected_amount_krw="100000",
            effective_from="2026-01-01",
        )
        # The premium changes in the middle of this month: the month counts once, at the new amount.
        raised = change_plan(
            client,
            actor,
            rising["id"],
            rising["version"],
            title="합성 인상 보험료",
            expected_amount_krw="120000",
            effective_from="2026-03-15",
        )
        assert raised.status_code == 200, raised.text
        steady = create_plan(
            client,
            actor,
            title="합성 해지 보험료",
            expected_amount_krw="50000",
            effective_from="2026-01-01",
        )
        create(f"/policies/{changed['id']}/premium-links", {"rule_id": rising["id"]})
        create(f"/policies/{ended['id']}/premium-links", {"rule_id": steady["id"]})
        stopped = client.patch(
            f"{base}/policies/{ended['id']}",
            headers={**actor.headers, "If-Match": '"1"'},
            json={"status": "ended"},
        )
        assert stopped.status_code == 200, stopped.text
        # The policy was ended in February; its plan item was never closed.
        with app.state.engine.begin() as connection:
            connection.execute(
                text("UPDATE insurance_policies SET updated_at = :at WHERE id = :id"),
                {"at": datetime(2026, 2, 10, tzinfo=UTC), "id": ended["id"]},
            )
        # A benefit on a policy whose premiums are unknown must not inflate the household ratio.
        case = create("/cases", case_payload(actor))
        money(
            client,
            actor,
            "/payouts",
            actual(
                "5000000", allocations=[allocation(case["id"], "5000000", policy_id=unpaid["id"])]
            ),
        )
        result = summary()
    rows = {row["policy_id"]: row for row in result["policies"]}
    assert rows[changed["id"]]["paid_estimated_krw"] == "320000"
    assert rows[changed["id"]]["estimated_months"] == 3
    assert rows[changed["id"]]["monthly_premium_krw"] == "120000"
    assert rows[ended["id"]]["paid_estimated_krw"] == "100000"
    assert rows[ended["id"]]["estimated_months"] == 2
    assert rows[ended["id"]]["monthly_premium_krw"] == "0"
    assert rows[unpaid["id"]]["paid_total_krw"] is None
    assert rows[unpaid["id"]]["received_krw"] == "5000000"
    assert result["paid_total_krw"] == "420000" and result["received_krw"] == "5000000"
    assert result["matched_received_krw"] == "0" and result["recovery_percent"] == "0.0"
    assert result["paid_unknown_count"] == 1
