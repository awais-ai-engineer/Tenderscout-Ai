from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ANALYSIS_SCHEMA_VERSION = "v1"


def validate_storage_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Output contains a NUL character")
    value.encode("utf-8")
    return value


Evidence = Annotated[
    str, Field(min_length=1, max_length=400), AfterValidator(validate_storage_text)
]
Claim = Annotated[
    str, Field(min_length=1, max_length=2000), AfterValidator(validate_storage_text)
]


class StrictOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class EvidenceItem(StrictOutput):
    value: Claim
    evidence: Evidence


class EvaluationCriterion(StrictOutput):
    criterion: Claim
    weighting: Claim | None
    notes: Claim | None
    evidence: Evidence


class ImportantDate(StrictOutput):
    label: Claim
    date: Claim | None
    notes: Claim | None
    evidence: Evidence


class ContactInformation(StrictOutput):
    name: Claim | None
    organization: Claim | None
    email: Claim | None
    phone: Claim | None
    role: Claim | None
    evidence: Evidence

    @model_validator(mode="after")
    def require_contact_detail(self) -> Self:
        if not any((self.name, self.organization, self.email, self.phone, self.role)):
            raise ValueError("Contact must contain at least one source detail")
        return self


class TenderAnalysisOutput(StrictOutput):
    summary: Claim | None = None
    summary_evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    eligibility_requirements: list[EvidenceItem] = Field(max_length=100)
    required_documents: list[EvidenceItem] = Field(max_length=100)
    technical_requirements: list[EvidenceItem] = Field(max_length=100)
    financial_requirements: list[EvidenceItem] = Field(max_length=100)
    submission_instructions: list[EvidenceItem] = Field(max_length=100)
    evaluation_criteria: list[EvaluationCriterion] = Field(max_length=100)
    important_dates: list[ImportantDate] = Field(max_length=100)
    contact_information: list[ContactInformation] = Field(max_length=100)
    risks_or_ambiguities: list[EvidenceItem] = Field(max_length=100)

    @model_validator(mode="after")
    def require_summary_evidence(self) -> Self:
        if bool(self.summary) != bool(self.summary_evidence):
            raise ValueError("Summary and its evidence must be supplied together")
        return self

    def evidence_snippets(self) -> list[str]:
        snippets = list(self.summary_evidence)
        for items in (
            self.eligibility_requirements,
            self.required_documents,
            self.technical_requirements,
            self.financial_requirements,
            self.submission_instructions,
            self.evaluation_criteria,
            self.important_dates,
            self.contact_information,
            self.risks_or_ambiguities,
        ):
            snippets.extend(item.evidence for item in items)
        return snippets
