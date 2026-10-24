"""Bounded literal name search on an already household-scoped metadata query."""

from typing import Annotated

from fastapi import Query
from sqlalchemy import or_

from sallimbook.core.errors import DomainError

NameQuery = Annotated[str | None, Query(max_length=120)]


def search_names(query, value, *columns):
    if value is None:
        return query
    if (
        not isinstance(value, str)
        or len(value) > 120
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DomainError(
            "VALIDATION_ERROR", "검색어는 제어문자 없이 120자까지 입력해 주세요.", 422
        )
    term = value.strip()
    if not term:
        return query
    # Treat %, _ and backslash as literal text; SQL values remain bound parameters.
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return query.where(or_(*(column.ilike(f"%{escaped}%", escape="\\") for column in columns)))
