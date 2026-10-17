from sqlalchemy import CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin


class Household(EntityMixin, Base):
    __tablename__ = "households"
    __table_args__ = (
        CheckConstraint("timezone = 'Asia/Seoul'", name="seoul_timezone"),
        CheckConstraint("base_currency = 'KRW'", name="krw_currency"),
        CheckConstraint("version > 0", name="positive_version"),
    )

    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(32), server_default=text("'Asia/Seoul'"))
    base_currency: Mapped[str] = mapped_column(String(3), server_default=text("'KRW'"))
