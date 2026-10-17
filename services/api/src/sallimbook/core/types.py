import calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, StringConstraints, TypeAdapter
from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

SEOUL = ZoneInfo("Asia/Seoul")
MAX_KRW = 10**20 - 1

KrwString = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,19})$", max_length=20)
]
SignedKrwString = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(0|-?[1-9][0-9]{0,19})$", max_length=21)
]


def _valid_month(value: str) -> str:
    date(int(value[:4]), int(value[5:]), 1)
    return value


YearMonth = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    AfterValidator(_valid_month),
]


def decimal_krw(value: str) -> Decimal:
    return Decimal(TypeAdapter(SignedKrwString).validate_python(value))


def krw_string(value: int | Decimal) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("KRW requires an integer or Decimal")
    amount = Decimal(value)
    if (
        not amount.is_finite()
        or amount != amount.to_integral_value()
        or amount.copy_abs() > MAX_KRW
    ):
        raise ValueError("KRW must be an integral amount within numeric(20,0)")
    return str(int(amount))


def month_start(value: str) -> date:
    month = TypeAdapter(YearMonth).validate_python(value)
    return date(int(month[:4]), int(month[5:]), 1)


def month_end(value: str) -> date:
    first = month_start(value)
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def seoul_month(moment: datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return moment.astimezone(SEOUL).strftime("%Y-%m")


class KrwNumeric(TypeDecorator[Decimal]):
    """Reject floats and fractional amounts before PostgreSQL can round them."""

    impl = Numeric(20, 0)
    cache_ok = True

    def process_bind_param(self, value: int | Decimal | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(krw_string(value))
