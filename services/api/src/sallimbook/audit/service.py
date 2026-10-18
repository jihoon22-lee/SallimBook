"""Metadata-only audit projection; raw safe_diff is never an API response."""

import base64
import binascii
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import get_args, get_type_hints
from uuid import UUID

from sqlalchemy import and_, or_, select

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.audit.schemas import AuditEventResponse, AuditListResponse
from sallimbook.core.audit import AuditEvent, record_event
from sallimbook.core.errors import DomainError
from sallimbook.exports.catalog import (
    PRIVATE_COLUMNS,
    PRIVATE_TABLES,
    PUBLIC_COLUMNS,
    SPECIAL_COLUMNS,
)
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import HouseholdMember

ENTITY_TYPES = frozenset(get_args(get_type_hints(record_event)["entity_type"]))
ACTIONS = frozenset(get_args(get_type_hints(record_event)["action"]))
KNOWN_FIELDS = (
    frozenset(
        field
        for mapping in (PUBLIC_COLUMNS, PRIVATE_COLUMNS, PRIVATE_TABLES)
        for fields in mapping.values()
        for field in fields
    )
    | frozenset(
        field
        for groups in SPECIAL_COLUMNS.values()
        for fields in groups.values()
        for field in fields
    )
    | {
        "scope",
        "sources",
        "replacements",
        "asset",
        "closure_ack",
        "closed_on",
        "target",
        "contains_no_card_data",
        "lines",
        "expense_ids",
        "cash",
        "copy_previous",
        "acknowledge_scope_change",
        "acknowledge_non_month_end_dates",
        "clear_next_check_override",
        "effective_on",
        "payment_basis",
        "usage_digest",
        "links",
        "member_wrapping",
        "recovery_wrapping",
        "wrappings",
        "key_check",
        "cards",
        "secret_envelope",
        "formats",
        "selected_documents",
        "account_number",
        "policy_number",
        "values",
        "settlements",
        "allocations",
        "expenses",
    }
)
AUDIT_COLUMNS = (
    "id",
    "actor_member_id",
    "entity_type",
    "entity_id",
    "action",
    "request_id",
    "before_version",
    "after_version",
    "occurred_at",
    "changed_fields",
)


def projection(household_id):
    return (
        select(
            AuditEvent.id,
            HouseholdMember.id.label("actor_member_id"),
            AuditEvent.entity_type,
            AuditEvent.entity_id,
            AuditEvent.action,
            AuditEvent.request_id,
            AuditEvent.before_version,
            AuditEvent.after_version,
            AuditEvent.occurred_at,
            AuditEvent.safe_diff,
        )
        .join(
            HouseholdMember,
            and_(
                HouseholdMember.household_id == AuditEvent.household_id,
                HouseholdMember.user_id == AuditEvent.actor_id,
            ),
        )
        .where(AuditEvent.household_id == household_id)
    )


def safe_row(row):
    values = dict(row)
    diff = values.pop("safe_diff")
    # Fail closed on historical corruption instead of reflecting arbitrary JSON or strings.
    if (
        not isinstance(diff, dict)
        or set(diff) != {"changed_fields"}
        or not isinstance(diff["changed_fields"], list)
        or len(diff["changed_fields"]) > 64
        or any(
            not isinstance(field, str) or field not in KNOWN_FIELDS
            for field in diff["changed_fields"]
        )
        or values["entity_type"] not in ENTITY_TYPES
        or values["action"] not in ACTIONS
        or (
            values["request_id"] is not None
            and not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", values["request_id"])
        )
    ):
        raise DomainError("AUDIT_METADATA_INVALID", "감사 기록 형식을 확인해 주세요.", 503)
    values["changed_fields"] = sorted(set(diff["changed_fields"]))
    return values


def _invalid_cursor():
    return DomainError("INVALID_CURSOR", "페이지 기준을 확인해 주세요.", 400)


def _encode(value):
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode(cursor, binding):
    try:
        if len(cursor) > 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
            raise ValueError
        decoded = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(decoded, list) or len(decoded) != 3 or _encode(decoded) != cursor:
            raise ValueError
        timestamp, identifier, fingerprint = decoded
        if fingerprint != binding:
            raise ValueError
        occurred = datetime.fromisoformat(timestamp)
        if occurred.tzinfo is None or occurred.utcoffset().total_seconds() != 0:
            raise ValueError
        return occurred, UUID(identifier)
    except ValueError, TypeError, AttributeError, binascii.Error:
        raise _invalid_cursor() from None


def list_events(
    session,
    principal,
    *,
    limit=50,
    cursor=None,
    entity_type=None,
    entity_id=None,
    actor_member_id=None,
    action=None,
    since=None,
    until=None,
):
    auth, devices = identity.lock_session_devices(session, principal)
    lock_asset_scope(session, principal)
    if entity_type is not None and entity_type not in ENTITY_TYPES:
        raise DomainError("INVALID_AUDIT_FILTER", "감사 대상 종류를 확인해 주세요.", 422)
    if action is not None and action not in ACTIONS:
        raise DomainError("INVALID_AUDIT_FILTER", "감사 동작을 확인해 주세요.", 422)
    if not 1 <= limit <= 200 or any(v is not None and v.tzinfo is None for v in (since, until)):
        raise DomainError("INVALID_AUDIT_FILTER", "조회 범위를 확인해 주세요.", 422)
    if since is not None and until is not None and since >= until:
        raise DomainError("INVALID_AUDIT_FILTER", "조회 범위를 확인해 주세요.", 422)
    if (
        actor_member_id is not None
        and session.scalar(
            select(HouseholdMember.id).where(
                HouseholdMember.id == actor_member_id,
                HouseholdMember.household_id == principal.household_id,
            )
        )
        is None
    ):
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    filters = [
        str(principal.household_id),
        entity_type,
        str(entity_id),
        str(actor_member_id),
        action,
        since.astimezone(UTC).isoformat() if since else None,
        until.astimezone(UTC).isoformat() if until else None,
    ]
    binding = hashlib.sha256(json.dumps(filters).encode()).hexdigest()
    query = projection(principal.household_id)
    for column, value in (
        (AuditEvent.entity_type, entity_type),
        (AuditEvent.entity_id, entity_id),
        (HouseholdMember.id, actor_member_id),
        (AuditEvent.action, action),
    ):
        if value is not None:
            query = query.where(column == value)
    if since is not None:
        query = query.where(AuditEvent.occurred_at >= since)
    if until is not None:
        query = query.where(AuditEvent.occurred_at < until)
    if cursor:
        occurred, identifier = _decode(cursor, binding)
        query = query.where(
            or_(
                AuditEvent.occurred_at < occurred,
                and_(AuditEvent.occurred_at == occurred, AuditEvent.id < identifier),
            )
        )
    rows = (
        session.execute(
            query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
        )
        .mappings()
        .all()
    )
    items = [AuditEventResponse(**safe_row(row)) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = _encode([last.occurred_at.astimezone(UTC).isoformat(), str(last.id), binding])
    identity.validate_locked_session(principal, auth, devices[principal.device_id])
    session.commit()
    return AuditListResponse(items=items, next_cursor=next_cursor)
