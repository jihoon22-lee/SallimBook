from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from sallimbook.assets.schemas import DateOnly
from sallimbook.identity.schemas import InputModel


class ReadableExport(InputModel):
    domains: list[
        Literal["assets", "accounts", "cards", "income", "fixed", "insurance", "homecare"]
    ] = Field(min_length=1, max_length=7)
    from_date: DateOnly | None = None
    through_date: DateOnly | None = None
    annual_year: int | None = Field(default=None, strict=True, ge=1, le=9999)

    @model_validator(mode="after")
    def valid_scope(self):
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("Domains must be unique")
        if self.from_date and self.through_date and self.from_date > self.through_date:
            raise ValueError("Invalid date range")
        if self.annual_year is not None and "insurance" not in self.domains:
            raise ValueError("Annual summary requires insurance domain")
        return self


class ExportRequest(InputModel):
    formats: list[Literal["json", "csv"]] = Field(
        default_factory=lambda: ["json", "csv"], max_length=2
    )
    readable: ReadableExport | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def unique_selections(self):
        if not self.formats and self.readable is None:
            raise ValueError("Select original or readable output")
        if len(self.formats) != len(set(self.formats)) or len(self.document_ids) != len(
            set(self.document_ids)
        ):
            raise ValueError("Selections must be unique")
        return self
