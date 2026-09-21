from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    BeforeValidator,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.ai.schemas import StrictOutput, validate_storage_text


def normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(validate_storage_text(value).split())
    return value


Name = Annotated[
    str, BeforeValidator(normalize_text), Field(min_length=1, max_length=255)
]
Description = Annotated[
    str, BeforeValidator(normalize_text), Field(min_length=1, max_length=10000)
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Count = Annotated[int, Field(ge=0, le=2147483647)]


class CapabilityInput(StrictOutput):
    name: Name
    description: Description | None = None


class CertificationInput(StrictOutput):
    name: Name
    issuer: Name | None = None
    identifier: Name | None = None
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("Certification dates are reversed")
        return self


class ExperienceInput(StrictOutput):
    title: Name | None = None
    client: Name | None = None
    description: Description | None = None
    country: Name | None = None
    contract_value: Money | None = None
    currency: Currency | None = None
    started_at: date | None = None
    completed_at: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if (
            self.started_at
            and self.completed_at
            and self.started_at > self.completed_at
        ):
            raise ValueError("Experience dates are reversed")
        if not any((self.title, self.description, self.client)):
            raise ValueError("Experience needs a title, description or client")
        return self


class CompanyInput(StrictOutput):
    name: Name
    description: Description | None = None
    country: Name | None = None
    website: Annotated[str, Field(max_length=2048)] | None = None
    employee_count: Count | None = None
    annual_revenue: Money | None = None
    currency: Currency | None = None
    years_in_business: Count | None = None
    capabilities_complete: bool = False
    certifications_complete: bool = False
    experience_complete: bool = False
    financials_complete: bool = False
    capabilities: list[CapabilityInput] = Field(default_factory=list, max_length=200)
    certifications: list[CertificationInput] = Field(
        default_factory=list, max_length=200
    )
    experience: list[ExperienceInput] = Field(default_factory=list, max_length=200)

    @field_validator("website")
    @classmethod
    def valid_website(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.username or url.password:
            raise ValueError("Website must not contain credentials")
        return str(url)

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        names = [item.name.casefold() for item in self.capabilities]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate capability names")
        return self
