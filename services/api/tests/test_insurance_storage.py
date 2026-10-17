"""Database preservation and valuation links independent of insurance API implementation."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import asset_payload, make_actor

from sallimbook.assets import service as assets
from sallimbook.assets.schemas import AssetCreate, AssetPatch
from sallimbook.core.errors import DomainError
from sallimbook.insurance.models import InsuranceCase, InsuranceCaseRevision, InsurancePolicy
from sallimbook.insurance.schemas import CaseInput


@pytest.fixture
def storage_actor(db_engine):
    return make_actor(db_engine)


@pytest.mark.database
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_case_history_rejects_database_mutation(db_engine, storage_actor, operation):
    actor = storage_actor
    values = CaseInput(
        title="합성 보존 사건", patient_member_id=actor.member_id, start_on="2026-01-01"
    ).model_dump()
    with Session(db_engine) as session:
        case = InsuranceCase(
            **values,
            household_id=actor.household_id,
            created_by_member_id=actor.member_id,
            updated_by_member_id=actor.member_id,
        )
        session.add(case)
        session.flush()
        revision = InsuranceCaseRevision(
            **values,
            household_id=actor.household_id,
            case_id=case.id,
            version=1,
            changed_by_member_id=actor.member_id,
            changed_at=datetime.now(UTC),
        )
        session.add(revision)
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            session.execute(
                update(InsuranceCaseRevision).values(title="합성 금지 변경")
                if operation == "update"
                else delete(InsuranceCaseRevision)
            )
        assert rejected.value.orig.sqlstate == "55000"
        session.rollback()


@pytest.mark.database
@pytest.mark.parametrize("patch", [{"kind": "liability"}, {"category": "other"}])
def test_policy_valuation_asset_stays_financial_but_can_close(db_engine, storage_actor, patch):
    actor = storage_actor
    with Session(db_engine) as session:
        asset = assets.prepare_asset(session, actor.principal, AssetCreate(**asset_payload()))
        policy = InsurancePolicy(
            household_id=actor.household_id,
            insurer="합성 보험사",
            product_name="합성 계약",
            coverage_start=date(2026, 1, 1),
            status="active",
            valuation_asset_id=asset.id,
            created_by_member_id=actor.member_id,
            updated_by_member_id=actor.member_id,
        )
        session.add(policy)
        session.commit()
        identifier, version = asset.id, asset.version
        with pytest.raises(DomainError) as rejected:
            assets.update_asset(
                session, actor.principal, identifier, AssetPatch(**patch), f'"{version}"'
            )
        assert rejected.value.code == "INSURANCE_ASSET_REQUIRED"
        session.rollback()
        ended = assets.update_asset(
            session, actor.principal, identifier, AssetPatch(ended_on="2026-01-31"), f'"{version}"'
        )
        assert ended.ended_on == date(2026, 1, 31)
        assert session.get(InsurancePolicy, policy.id).valuation_asset_id == identifier
