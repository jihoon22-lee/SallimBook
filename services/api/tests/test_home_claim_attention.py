"""The home task is unlinked in every policy; the per-policy selection stays explicit."""

import pytest
from fastapi.testclient import TestClient
from test_insurance_events import actors as actors
from test_insurance_events import app as app
from test_insurance_events import create_metadata, new_case, new_expense, new_node, new_policy


@pytest.mark.database
def test_any_policy_review_filter_does_not_change_per_policy_rules_or_duplicate_expenses(
    app, actors
):
    actor, _, foreign = actors
    with TestClient(app) as client:
        case = new_case(client, actor)
        node = new_node(client, actor, case)
        expenses = [new_expense(client, actor, case, node) for _ in range(3)]
        policies = [new_policy(client, actor) for _ in range(2)]
        for policy in policies:
            create_metadata(
                client,
                actor,
                "/claims",
                {
                    "case_id": case["id"],
                    "policy_id": policy["id"],
                    "expense_ids": [expenses[0]["id"]],
                    "claim_state": "draft",
                },
            )
        other_case = new_case(client, foreign)
        other_node = new_node(client, foreign, other_case)
        other = new_expense(client, foreign, other_case, other_node)
        path = "/api/v1/insurance/medical-expenses"
        query = {"state": "active", "unclaimed_any_policy": "true", "limit": 1}
        first = client.get(path, headers=actor.headers, params=query)
        assert first.status_code == 200, first.text
        assert first.json()["next_cursor"]
        second = client.get(
            path, headers=actor.headers, params=query | {"cursor": first.json()["next_cursor"]}
        )
        rows = first.json()["items"] + second.json()["items"]
        assert {row["id"] for row in rows} == {row["id"] for row in expenses[1:]}
        assert second.json()["next_cursor"] is None
        for bad in (
            {"claimed": "false"},
            query | {"claimed": "false"},
            query | {"claim_policy_id": policies[0]["id"]},
        ):
            assert client.get(path, headers=actor.headers, params=bad).status_code == 422
        per_policy = client.get(
            path,
            headers=actor.headers,
            params={"claimed": "true", "claim_policy_id": policies[0]["id"]},
        ).json()
        assert [row["id"] for row in per_policy["items"]] == [expenses[0]["id"]]
        assert client.get(path, params=query).status_code == 401
        assert (
            client.get(
                path, headers=actor.headers, params=query | {"cursor": other["id"]}
            ).status_code
            == 404
        )
        assert [
            row["id"]
            for row in client.get(path, headers=foreign.headers, params=query).json()["items"]
        ] == [other["id"]]
