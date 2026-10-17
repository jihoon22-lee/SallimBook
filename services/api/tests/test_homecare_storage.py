"""Direct stock-storage invariants independent of the homecare API."""

from datetime import date

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import make_actor

from sallimbook.homecare.models import (
    Appliance,
    ApplianceConsumable,
    Consumable,
    ConsumableReplacement,
    StockMovement,
)

pytestmark = pytest.mark.database


def actor_fields(actor):
    return dict(
        household_id=actor.household_id,
        created_by_member_id=actor.member_id,
        updated_by_member_id=actor.member_id,
    )


@pytest.fixture
def context(db_engine):
    actor = make_actor(db_engine)
    with Session(db_engine) as session:
        item = Consumable(name="합성 필터", unit="개", low_stock_threshold=1, **actor_fields(actor))
        appliance = Appliance(name="합성 기기", **actor_fields(actor))
        session.add_all([item, appliance])
        session.flush()
        link = ApplianceConsumable(
            appliance_id=appliance.id,
            consumable_id=item.id,
            interval_unit="manual",
            quantity_per_replacement=1,
            active=True,
            **actor_fields(actor),
        )
        session.add(link)
        session.commit()
        return actor, item.id, link.id


def movement(session, context, delta, kind="receipt", reversal_of=None):
    actor, item_id, _ = context
    item = session.get(Consumable, item_id)
    item.stock_quantity += delta
    item.version += 1
    session.flush()
    row = StockMovement(
        household_id=actor.household_id,
        created_by_member_id=actor.member_id,
        consumable_id=item_id,
        kind=kind,
        quantity_delta=delta,
        occurred_on=date(2026, 1, 1),
        reversal_of=reversal_of,
        reason="합성 재고 기록",
        stock_version=item.version,
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("side", ["cache_only", "movement_only"])
def test_committed_stock_equals_ledger_even_for_direct_writes(db_engine, context, side):
    actor, item_id, _ = context
    with Session(db_engine) as session:
        if side == "cache_only":
            session.execute(
                update(Consumable)
                .where(Consumable.id == item_id)
                .values(stock_quantity=1, version=2)
            )
        else:
            session.add(
                StockMovement(
                    household_id=actor.household_id,
                    created_by_member_id=actor.member_id,
                    consumable_id=item_id,
                    kind="receipt",
                    quantity_delta=1,
                    occurred_on=date(2026, 1, 1),
                    stock_version=1,
                )
            )
        with pytest.raises(DBAPIError) as rejected:
            session.commit()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        assert session.get(Consumable, item_id).stock_quantity == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


@pytest.mark.parametrize(
    "target",
    [
        "movement_update",
        "movement_delete",
        "replacement_update",
        "replacement_delete",
        "unit",
        "link_target",
    ],
)
def test_history_and_quantity_meaning_cannot_be_overwritten(db_engine, context, target):
    actor, item_id, link_id = context
    with Session(db_engine) as session:
        movement(session, context, 3)
        used = movement(session, context, -1, "replacement")
        replacement = ConsumableReplacement(
            household_id=actor.household_id,
            created_by_member_id=actor.member_id,
            appliance_consumable_id=link_id,
            consumable_id=item_id,
            stock_movement_id=used.id,
            replaced_on=used.occurred_on,
            quantity=1,
        )
        session.add(replacement)
        alternative = Consumable(
            name="합성 다른 필터", unit="개", low_stock_threshold=0, **actor_fields(actor)
        )
        session.add(alternative)
        session.commit()
        statement = {
            "movement_update": update(StockMovement).values(quantity_delta=2),
            "movement_delete": delete(StockMovement).where(StockMovement.id == used.id),
            "replacement_update": update(ConsumableReplacement).values(
                replaced_on=date(2026, 1, 2)
            ),
            "replacement_delete": delete(ConsumableReplacement),
            "unit": update(Consumable)
            .where(Consumable.id == item_id)
            .values(unit="상자", version=4),
            "link_target": update(ApplianceConsumable)
            .where(ApplianceConsumable.id == link_id)
            .values(consumable_id=alternative.id, version=2),
        }[target]
        with pytest.raises(DBAPIError) as rejected:
            session.execute(statement)
        assert rejected.value.orig.sqlstate == "55000"
        session.rollback()
        assert session.get(Consumable, item_id).stock_quantity == 2


@pytest.mark.parametrize("delta", [-2, 3])
def test_reversal_must_exactly_negate_its_original(db_engine, context, delta):
    with Session(db_engine) as session:
        original = movement(session, context, 3)
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            movement(session, context, delta, "reversal", original.id)
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        assert session.get(Consumable, context[1]).stock_quantity == 3


def test_reversal_cannot_reverse_a_reversal_or_repeat_an_original(db_engine, context):
    with Session(db_engine) as session:
        original = movement(session, context, 3)
        session.commit()
        reversed_row = movement(session, context, -3, "reversal", original.id)
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            movement(session, context, 3, "reversal", reversed_row.id)
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        movement(session, context, 3)
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            movement(session, context, -3, "reversal", original.id)
        assert rejected.value.orig.sqlstate == "23505"
        session.rollback()


def test_replacement_usage_cannot_commit_without_device_evidence(db_engine, context):
    with Session(db_engine) as session:
        movement(session, context, 3)
        session.commit()
        movement(session, context, -1, "replacement")
        with pytest.raises(DBAPIError) as rejected:
            session.commit()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        assert session.get(Consumable, context[1]).stock_quantity == 3


@pytest.mark.parametrize("change", [{"quantity": 2}, {"replaced_on": date(2026, 1, 2)}])
def test_replacement_evidence_matches_usage_amount_and_date(db_engine, context, change):
    actor, item_id, link_id = context
    with Session(db_engine) as session:
        movement(session, context, 3)
        session.commit()
        used = movement(session, context, -1, "replacement")
        fields = dict(
            household_id=actor.household_id,
            created_by_member_id=actor.member_id,
            appliance_consumable_id=link_id,
            consumable_id=item_id,
            stock_movement_id=used.id,
            replaced_on=used.occurred_on,
            quantity=1,
        )
        session.add(ConsumableReplacement(**(fields | change)))
        with pytest.raises(DBAPIError) as rejected:
            session.flush()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()


def test_stock_receipt_version_is_unique_and_captured_from_locked_item(db_engine, context):
    actor, item_id, _ = context
    with Session(db_engine) as session:
        original = movement(session, context, 3)
        session.commit()
        for version, code in [(1, "23514"), (original.stock_version, "23505")]:
            session.add(
                StockMovement(
                    household_id=actor.household_id,
                    created_by_member_id=actor.member_id,
                    consumable_id=item_id,
                    kind="receipt",
                    quantity_delta=1,
                    occurred_on=date(2026, 1, 1),
                    stock_version=version,
                )
            )
            with pytest.raises(DBAPIError) as rejected:
                session.flush()
            assert rejected.value.orig.sqlstate == code
            session.rollback()
