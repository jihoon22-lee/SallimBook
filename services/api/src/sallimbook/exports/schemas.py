from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from sallimbook.identity.schemas import InputModel


class ExportRequest(InputModel):
    formats: list[Literal["json", "csv"]] = Field(
        default_factory=lambda: ["json", "csv"], min_length=1, max_length=2
    )
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def unique_selections(self):
        if len(self.formats) != len(set(self.formats)) or len(self.document_ids) != len(
            set(self.document_ids)
        ):
            raise ValueError("Selections must be unique")
        return self
