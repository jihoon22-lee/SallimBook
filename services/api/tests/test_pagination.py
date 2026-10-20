"""Synthetic household keyset pagination across tied sort values."""

from datetime import UTC, datetime
from functools import partial
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_accounts import make_actor

from sallimbook.core.errors import DomainError
from sallimbook.core.pagination import keyset_page, page_after
from sallimbook.homecare.models import Appliance

T1, T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)


def uid(n):
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


def seed(session, actor, rows):
    for n, created in rows:
        session.add(
            Appliance(
                id=uid(n),
                household_id=actor.household_id,
                created_by_member_id=actor.member_id,
                updated_by_member_id=actor.member_id,
                name=f"합성 기기 {n}",
                created_at=created,
            )
        )
    session.commit()


def walk(session, actor, descending):
    query = select(Appliance).where(Appliance.household_id == actor.household_id)
    pages, cursor = [], None
    while True:
        rows, cursor = keyset_page(
            session,
            query,
            model=Appliance,
            household_id=actor.household_id,
            keys=(Appliance.created_at,),
            cursor=cursor,
            limit=2,
            descending=descending,
        )
        pages.append([row.id for row in rows])
        if cursor is None:
            return pages
        assert cursor == rows[-1].id


@pytest.mark.database
def test_keyset_page_breaks_ties_by_id_across_page_boundaries(db_engine):
    actor, foreign = make_actor(db_engine), make_actor(db_engine)
    with Session(db_engine) as session:
        seed(session, actor, [(5, T1), (1, T2), (4, T2), (2, T2), (3, T1)])
        seed(session, foreign, [(6, T2)])
        assert walk(session, actor, True) == [[uid(4), uid(2)], [uid(1), uid(5)], [uid(3)]]
        assert walk(session, actor, False) == [[uid(3), uid(5)], [uid(1), uid(2)], [uid(4)]]


@pytest.mark.database
def test_keyset_page_rejects_missing_foreign_or_out_of_scope_cursor(db_engine):
    actor = make_actor(db_engine)
    spouse, foreign = make_actor(db_engine, actor.household_id), make_actor(db_engine)
    with Session(db_engine) as session:
        seed(session, actor, [(1, T1)])
        seed(session, spouse, [(3, T2)])
        seed(session, foreign, [(2, T1)])
        query = select(Appliance).where(Appliance.household_id == actor.household_id)
        page = partial(
            keyset_page,
            session,
            query,
            model=Appliance,
            household_id=actor.household_id,
            keys=(Appliance.created_at,),
            limit=2,
        )
        assert [row.id for row in page(cursor=uid(3))[0]] == [uid(1)]
        mine = (Appliance.created_by_member_id == actor.member_id,)
        for cursor, where in ((uid(2), ()), (uid(9), ()), (uid(3), mine)):
            with pytest.raises(DomainError) as error:
                page(cursor=cursor, cursor_where=where)
            assert (error.value.code, error.value.status) == ("NOT_FOUND", 404)
        for limit in (0, 201, True):
            with pytest.raises(DomainError) as error:
                page(cursor=None, limit=limit)
            assert error.value.code == "INVALID_PAGE_SIZE"
            assert error.value.safe_message == "목록 크기를 확인해 주세요."


def test_page_after_continues_after_the_cursor_row_and_rejects_unknown_cursor():
    rows = [uid(3), uid(1), uid(2)]
    assert page_after(rows, cursor=None, limit=2, key=lambda row: row) == ([uid(3), uid(1)], uid(1))
    assert page_after(rows, cursor=uid(1), limit=2, key=lambda row: row) == ([uid(2)], None)
    with pytest.raises(DomainError) as error:
        page_after(rows, cursor=uid(9), limit=2, key=lambda row: row)
    assert (error.value.code, error.value.status) == ("NOT_FOUND", 404)


def api_pages(client, actor, path, *, items="items", cursor_key="id", **params):
    """Read every limit=2 page; each next_cursor must be the last row of its page."""
    pages, cursor = [], None
    while True:
        query = params | {"limit": 2} | ({"cursor": cursor} if cursor else {})
        response = client.get(path, headers=actor.headers, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body[items])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
        assert cursor == body[items][-1][cursor_key]
        assert len(pages) < 10, "pagination did not finish"


def ids(pages, key="id"):
    return [[row[key] for row in page] for page in pages]


def pairs(values):
    return [list(values[index : index + 2]) for index in range(0, len(values), 2)]
