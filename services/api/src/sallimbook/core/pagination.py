"""Household keyset pages that keep the UUID cursor shape while ordering by business keys."""

from collections.abc import Callable, Sequence
from operator import attrgetter
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, literal, select, tuple_
from sqlalchemy.orm import Session

from sallimbook.core.database import Base
from sallimbook.core.errors import DomainError

MAX_PAGE_SIZE = 200


def check_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise DomainError("INVALID_PAGE_SIZE", "목록 크기를 확인해 주세요.", 422)


def _missing_cursor() -> DomainError:
    return DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)


def keyset_page(
    session: Session,
    query: Select,
    *,
    model: type[Base],
    household_id: UUID,
    keys: Sequence[ColumnElement[Any]],
    cursor: UUID | None,
    limit: int,
    descending: bool = True,
    scalars: bool = True,
    cursor_of: Callable[[Any], UUID] = attrgetter("id"),
    cursor_where: Sequence[ColumnElement[bool]] = (),
) -> tuple[list[Any], UUID | None]:
    """Read one page after the cursor row; keys must be NOT NULL and id breaks every tie.

    The cursor row is re-read within the household (and `cursor_where` ownership) but without
    the list filters, so a row that left a status filter still marks a valid position.
    """
    check_limit(limit)
    order = (*keys, model.id)
    if cursor is not None:
        values = session.execute(
            select(*keys)
            .select_from(model)
            .where(model.id == cursor, model.household_id == household_id, *cursor_where)
        ).one_or_none()
        if values is None:
            raise _missing_cursor()
        position = tuple_(
            *(literal(value, key.type) for value, key in zip(values, keys, strict=True)),
            literal(cursor, model.id.type),
        )
        query = query.where(tuple_(*order) < position if descending else tuple_(*order) > position)
    query = query.order_by(*(c.desc() if descending else c.asc() for c in order)).limit(limit + 1)
    rows = list(session.scalars(query) if scalars else session.execute(query))
    return rows[:limit], cursor_of(rows[limit - 1]) if len(rows) > limit else None


def page_after[T](
    rows: Sequence[T], *, cursor: UUID | None, limit: int, key: Callable[[T], UUID]
) -> tuple[list[T], UUID | None]:
    """Slice an already ordered in-memory list after the row whose key is the cursor."""
    check_limit(limit)
    start = 0
    if cursor is not None:
        start = next((i + 1 for i, row in enumerate(rows) if key(row) == cursor), None)
        if start is None:
            raise _missing_cursor()
    page = list(rows[start : start + limit])
    return page, key(page[-1]) if start + limit < len(rows) else None
