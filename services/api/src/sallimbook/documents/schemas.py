import unicodedata
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sallimbook.cashflow.schemas import InputModel, Reason
from sallimbook.documents.models import MAX_DOCUMENT_BYTES
from sallimbook.insurance.schemas import EntityResponse

type DocumentKind = Literal[
    "policy", "case", "medical_node", "expense", "claim", "appliance", "asset"
]
type DocumentState = Literal["pending", "ready", "deleted"]
type DocumentMime = Literal["application/pdf", "image/jpeg", "image/png"]
Checksum = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class DocumentTarget(InputModel):
    kind: DocumentKind
    id: UUID


class DocumentCreate(InputModel):
    original_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=255)]
    mime_type: DocumentMime
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_DOCUMENT_BYTES)]
    checksum_sha256: Checksum
    target: DocumentTarget
    contains_no_card_data: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def filename(self) -> Self:
        if self.contains_no_card_data is not True:
            raise ValueError("Card images or card secrets cannot be attached")
        name = self.original_name
        if (
            name != name.strip()
            or name in {".", ".."}
            or any(c in "/\\" or unicodedata.category(c) in {"Cc", "Cf"} for c in name)
        ):
            raise ValueError("Use a filename without path or control characters")
        extensions = {
            "application/pdf": {"pdf"},
            "image/jpeg": {"jpg", "jpeg"},
            "image/png": {"png"},
        }
        if "." not in name or name.rsplit(".", 1)[1].lower() not in extensions[self.mime_type]:
            raise ValueError("The filename extension must match the declared document type")
        return self


class DocumentResponse(EntityResponse):
    original_name: str
    mime_type: DocumentMime
    size_bytes: int
    checksum_sha256: str
    state: DocumentState
    pending_expires_at: datetime
    stored_at: datetime | None
    orphaned_at: datetime | None
    deleted_at: datetime | None
    active_link_count: int = Field(ge=0)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    next_cursor: UUID | None


class DocumentLinkCreate(InputModel):
    document_id: UUID
    target: DocumentTarget


class DocumentLinkResponse(EntityResponse):
    document_id: UUID
    target: DocumentTarget
    active: bool
    ended_at: datetime | None
    end_reason: str | None


class DocumentLinkListResponse(BaseModel):
    items: list[DocumentLinkResponse]
    next_cursor: UUID | None


class DocumentReason(InputModel):
    reason: Reason = Field(repr=False)


class DocumentMutationReference(BaseModel):
    id: UUID
    version: int = Field(ge=1)
