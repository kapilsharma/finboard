"""API contract (request/response models). Separate from ORM models on purpose (ADR-0007)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from finboard.domain.enums import AccountType, CategoryType, JobStatus, Theme

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Colour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
MaskedNumber = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{1,4}$"), Field(description="Last 4 digits only")
]
ParserId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatchModel(InputModel):
    """PATCH bodies: only fields that were sent are applied. Listed fields can't be set to null."""

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required(self) -> Self:
        for field in self.not_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"'{field}' can't be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class OutputModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- accounts


class AccountCreate(InputModel):
    name: Name
    type: AccountType
    institution: Name | None = None
    masked_number: MaskedNumber | None = None
    parser_id: ParserId | None = None
    active: bool = True
    colour: Colour | None = None


class AccountUpdate(PatchModel):
    not_nullable = frozenset({"name", "type", "active"})

    name: Name | None = None
    type: AccountType | None = None
    institution: Name | None = None
    masked_number: MaskedNumber | None = None
    parser_id: ParserId | None = None
    active: bool | None = None
    colour: Colour | None = None


class AccountOut(OutputModel):
    id: uuid.UUID
    name: str
    type: AccountType
    institution: str | None
    masked_number: str | None
    parser_id: str | None
    currency: str
    active: bool
    colour: str | None
    created_at: datetime
    updated_at: datetime


class AccountList(BaseModel):
    items: list[AccountOut]


# ---------------------------------------------------------------- categories


class CategoryCreate(InputModel):
    name: CategoryName
    type: CategoryType
    parent_id: uuid.UUID | None = None
    colour: Colour | None = None


class CategoryUpdate(PatchModel):
    not_nullable = frozenset({"name", "type", "sort_order", "archived"})

    name: CategoryName | None = None
    type: CategoryType | None = None
    parent_id: uuid.UUID | None = None
    colour: Colour | None = None
    sort_order: int | None = None
    archived: bool | None = None


class CategoryOut(OutputModel):
    id: uuid.UUID
    name: str
    type: CategoryType
    parent_id: uuid.UUID | None
    colour: str | None
    is_system: bool
    system_key: str | None
    sort_order: int
    archived: bool


class CategoryList(BaseModel):
    items: list[CategoryOut]


# ---------------------------------------------------------------- jobs


class JobOut(OutputModel):
    id: uuid.UUID
    kind: str
    status: JobStatus
    progress: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[JobOut]


# ---------------------------------------------------------------- me / meta / settings


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    mode: str


class MetaOut(BaseModel):
    version: str
    api_version: str
    mode: str


class Preferences(BaseModel):
    theme: Theme


class PreferencesUpdate(PatchModel):
    not_nullable = frozenset({"theme"})

    theme: Theme | None = None


class HealthOut(BaseModel):
    status: str
    checks: dict[str, str] = {}
