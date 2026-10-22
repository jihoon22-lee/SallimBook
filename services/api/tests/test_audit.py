"""Audit vocabulary: writes only register readable names and reads fail closed on the rest."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from sallimbook.audit.service import KNOWN_FIELDS, safe_row
from sallimbook.core.audit import AuditEvent, record_event
from sallimbook.core.authorization import Principal
from sallimbook.core.errors import DomainError


def principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        member_id=uuid4(),
        household_id=uuid4(),
        session_id=uuid4(),
        device_id=uuid4(),
        role="owner",
        transport="native",
        authenticated_at=datetime.now(UTC),
    )


def stored_row(changed_fields):
    """A projected audit row as the list and export queries read it."""
    return {
        "id": uuid4(),
        "actor_member_id": uuid4(),
        "entity_type": "cash_record",
        "entity_id": uuid4(),
        "action": "create",
        "request_id": None,
        "before_version": None,
        "after_version": 1,
        "occurred_at": datetime.now(UTC),
        "safe_diff": {"changed_fields": changed_fields},
    }


def test_audit_read_skips_legacy_duplicate_acknowledged_field():
    # Income entries written before the fix recorded the request flag as a changed field.
    row = safe_row(stored_row(["duplicate_acknowledged", "amount_krw"]))
    assert row["changed_fields"] == ["amount_krw"]
    assert "duplicate_acknowledged" not in KNOWN_FIELDS


def test_audit_read_still_fails_closed_for_other_unknown_names():
    for unknown in ("not_a_known_field", "reason_text", "Amount"):
        with pytest.raises(DomainError) as invalid:
            safe_row(stored_row(["amount_krw", unknown]))
        assert invalid.value.code == "AUDIT_METADATA_INVALID"
        assert invalid.value.status == 503


def test_record_event_rejects_unregistered_field_names():
    with Session() as session:
        with pytest.raises(ValueError, match="registered"):
            record_event(
                session,
                principal(),
                entity_type="cash_record",
                entity_id=uuid4(),
                action="create",
                before_version=None,
                after_version=1,
                changed_fields=("not_a_known_field",),
            )
        assert not session.new
        # The request flag that once broke the audit list is not a registered name.
        with pytest.raises(ValueError, match="registered"):
            record_event(
                session,
                principal(),
                entity_type="cash_record",
                entity_id=uuid4(),
                action="create",
                before_version=None,
                after_version=1,
                changed_fields=("amount_krw", "duplicate_acknowledged"),
            )
        assert not session.new


def test_record_event_accepts_registered_field_names():
    with Session() as session:
        event = record_event(
            session,
            principal(),
            entity_type="cash_record",
            entity_id=uuid4(),
            action="create",
            before_version=None,
            after_version=1,
            changed_fields=("amount_krw", "period_month"),
        )
        assert isinstance(event, AuditEvent)
        assert event.safe_diff == {"changed_fields": ["amount_krw", "period_month"]}
