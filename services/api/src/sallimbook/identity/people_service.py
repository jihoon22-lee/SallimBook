from datetime import UTC, datetime

from sqlalchemy import select

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.pagination import keyset_page
from sallimbook.identity.auth_models import HouseholdMember, User
from sallimbook.identity.people_models import HouseholdPerson
from sallimbook.identity.people_schemas import (
    PersonCreatedReference,
    PersonListResponse,
    PersonResponse,
)


def person_response(session, row):
    values = {key: getattr(row, key) for key in PersonResponse.model_fields if key != "active"}
    active = row.archived_at is None
    if row.member_id is not None:
        member, user = session.execute(
            select(HouseholdMember, User)
            .join(User, User.id == HouseholdMember.user_id)
            .where(
                HouseholdMember.household_id == row.household_id,
                HouseholdMember.id == row.member_id,
            )
        ).one()
        values["display_name"] = user.display_name
        active = member.status == "active" and user.disabled_at is None
    return PersonResponse(**values, active=active)


def require_person(session, principal, person_id, *, active=True):
    if person_id is None:
        return None
    row = scoped_entity(session, HouseholdPerson, person_id, principal, for_update=active)
    if active and not person_response(session, row).active:
        raise DomainError("PERSON_UNAVAILABLE", "사용 중인 가족을 선택해 주세요.", 422)
    return row


def require_people_client(session, principal, previous_id, candidate_id, supported):
    # Capability describes the picker, never permissions. Protect cached old web as well as APKs.
    if supported or candidate_id == previous_id:
        return
    for identifier in (previous_id, candidate_id):
        row = require_person(session, principal, identifier, active=False)
        if row is not None and row.member_id is None:
            raise DomainError(
                "PEOPLE_CLIENT_REQUIRED",
                "가족 정보를 바꾸려면 앱을 업데이트하거나 웹을 새로 열어 주세요.",
                422,
            )


def list_people(session, principal, *, cursor=None, limit=50):
    rows, next_cursor = keyset_page(
        session,
        select(HouseholdPerson).where(HouseholdPerson.household_id == principal.household_id),
        model=HouseholdPerson,
        household_id=principal.household_id,
        keys=(HouseholdPerson.created_at,),
        cursor=cursor,
        limit=limit,
    )
    result = PersonListResponse(
        items=[person_response(session, row) for row in rows], next_cursor=next_cursor
    )
    session.commit()
    return result


def create_person(session, principal, payload, key):
    lock_asset_scope(session, principal)

    def execute():
        row = HouseholdPerson(
            **payload.model_dump(),
            household_id=principal.household_id,
            created_by_member_id=principal.member_id,
            updated_by_member_id=principal.member_id,
        )
        session.add(row)
        session.flush()
        record_event(
            session,
            principal,
            entity_type="household_person",
            entity_id=row.id,
            action="create",
            before_version=None,
            after_version=row.version,
            changed_fields=payload.model_fields_set,
        )
        return IdempotentResult(row.id, "household_person", row.version)

    result = run_idempotent(
        session, principal, "people.create", key, payload.model_dump(mode="json"), execute
    )
    session.commit()
    return PersonCreatedReference(id=result.resource_id, version=result.resource_version)


def update_person(session, principal, person_id, payload, if_match):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, HouseholdPerson, person_id, principal, for_update=True)
    require_version(row, if_match)
    if row.member_id is not None:
        raise DomainError(
            "MEMBER_PERSON_MANAGED", "로그인 구성원 정보는 계정 설정에서 바꿔 주세요.", 422
        )
    before = row.version
    fields = payload.model_dump(exclude_unset=True)
    if "active" in fields:
        row.archived_at = None if fields.pop("active") else row.archived_at or datetime.now(UTC)
    for name, value in fields.items():
        setattr(row, name, value)
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="household_person",
        entity_id=row.id,
        action="update",
        before_version=before,
        after_version=row.version,
        changed_fields=(payload.model_fields_set - {"active"})
        | ({"archived_at"} if "active" in payload.model_fields_set else set()),
    )
    result = person_response(session, row)
    session.commit()
    return result
