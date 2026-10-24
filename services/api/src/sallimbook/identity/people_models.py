"""Household people are insurance subjects, never authentication principals."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin


class HouseholdPerson(EntityMixin, Base):
    __tablename__ = "household_people"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("member_id"),
        ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="RESTRICT"),
        *(
            ForeignKeyConstraint(
                ["household_id", field],
                ["household_members.household_id", "household_members.id"],
                ondelete="RESTRICT",
                name=f"fk_household_people_{field}",
            )
            for field in ("member_id", "created_by_member_id", "updated_by_member_id")
        ),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "(member_id IS NOT NULL AND id = member_id AND display_name IS NULL "
            "AND relation = 'member' AND archived_at IS NULL) OR "
            "(member_id IS NULL AND display_name IS NOT NULL "
            "AND char_length(btrim(display_name)) > 0 AND relation IN ('child','parent','other'))",
            name="person_kind",
        ),
    )
    household_id: Mapped[UUID]
    member_id: Mapped[UUID | None]
    display_name: Mapped[str | None] = mapped_column(String(120))
    relation: Mapped[str] = mapped_column(String(8))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]


def add_member_person(session, member):
    """Call after membership INSERT, in the same registration transaction."""
    session.add(
        HouseholdPerson(
            id=member.id,
            household_id=member.household_id,
            member_id=member.id,
            relation="member",
            created_by_member_id=member.id,
            updated_by_member_id=member.id,
        )
    )
    session.flush()
