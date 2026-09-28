from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.ai.schemas import TenderAnalysisOutput
from app.schemas.company import CompanyInput
from app.services.retrieval import normalize_question

ID = Annotated[int, Field(gt=0)]
SourceSlug = Literal["contracts-finder", "find-a-tender", "ted"]


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def aware_timestamps(cls, value):
        if isinstance(value, datetime):
            from app.services.change_rules import utc_datetime

            return utc_datetime(value)
        return value


class Page[T](Response):
    items: list[T] = Field(max_length=100)
    next_cursor: int | None = None


class ErrorDetail(Response):
    code: str
    message: str


class ErrorEnvelope(Response):
    error: ErrorDetail


class TenderSummary(Response):
    id: ID
    source: str
    external_id: str | None
    title: str
    organization: str | None
    category: str | None
    location: str | None
    published_at: datetime | None
    deadline: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    latest_revision_index: int
    document_count: int
    latest_analysis_status: str | None


class DiscoverTender(TenderSummary):
    freshly_fetched: bool


class DiscoverSource(Response):
    source: SourceSlug
    status: Literal["success", "unavailable"]
    fetched_at: datetime | None = None
    error_code: Literal["source_unavailable"] | None = None


class DiscoverResponse(Response):
    items: list[DiscoverTender] = Field(max_length=100)
    next_cursor: int | None = None
    requested_at: datetime
    mode: Literal["live", "recorded"]
    sources: list[DiscoverSource]
    result_count: int


class AnalysisSummary(Response):
    id: ID
    document_version_id: ID
    status: Literal["completed", "failed"]
    model: str
    created_at: datetime


class Revision(Response):
    revision_id: ID
    revision_index: int
    observed_at: datetime
    deadline: datetime | None
    snapshot_hash: str


class ChangeSummary(Response):
    id: ID
    tender_id: ID
    kind: Literal["metadata", "document"]
    change_count: int
    created_at: datetime


class DocumentVersionSummary(Response):
    id: ID
    content_hash: str
    byte_size: int
    media_type: str | None
    downloaded_at: datetime
    extraction_status: str
    has_analysis: bool
    is_indexed: bool


class DocumentSummary(Response):
    id: ID
    title: str | None
    media_type: str | None
    versions: Page[DocumentVersionSummary]


class TenderDetail(TenderSummary):
    description: str | None
    description_truncated: bool
    source_url: str
    latest_revision: Revision | None
    documents: Page[DocumentSummary]
    analyses: Page[AnalysisSummary]
    latest_metadata_change: ChangeSummary | None
    matches_count: int


class AnalysisDetail(AnalysisSummary):
    analysis_schema_version: str
    provider: str
    prompt_version: str
    facts: TenderAnalysisOutput | None


class CompanySummary(Response):
    id: ID
    name: str
    country: str | None
    capability_count: int
    certification_count: int
    experience_count: int
    capabilities_complete: bool
    certifications_complete: bool
    experience_complete: bool
    financials_complete: bool


class CompanyDetail(Response):
    id: ID
    profile: CompanyInput


class MatchRequest(Response):
    company_id: ID
    analysis_id: ID


class RequirementMatch(Response):
    requirement: str
    status: str
    company_fact: JsonValue
    reason: str
    tender_evidence: str
    hard_requirement: bool
    category: str


class MatchRisk(Response):
    kind: str
    reason: str
    tender_evidence: str | None


class MatchSummary(Response):
    match_id: ID
    company_id: ID
    analysis_id: ID
    eligibility_status: str
    score: int | None = Field(
        ge=0, le=100, description="Heuristic alignment score, not win probability"
    )
    coverage_ratio: float = Field(ge=0, le=1)
    created_at: datetime


class MatchDetail(MatchSummary):
    reused: bool = False
    hard_blockers: list[RequirementMatch] = Field(max_length=1000)
    matched_requirements: list[RequirementMatch] = Field(max_length=1000)
    unmatched_requirements: list[RequirementMatch] = Field(max_length=1000)
    unknown_requirements: list[RequirementMatch] = Field(max_length=1000)
    capability_matches: list[RequirementMatch] = Field(max_length=1000)
    certification_matches: list[RequirementMatch] = Field(max_length=1000)
    experience_matches: list[RequirementMatch] = Field(max_length=1000)
    risks: list[MatchRisk] = Field(max_length=102)


class AskRequest(Response):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        return normalize_question(value)


class Citation(Response):
    document_version_id: ID
    chunk_id: ID
    chunk_index: int
    quote: str


class Answer(Response):
    question_id: ID
    status: Literal["completed", "insufficient"]
    answer: str | None
    citations: list[Citation] = Field(max_length=20)
    reused: bool


class ChangeRecord(Response):
    field: str | None = None
    category: str | None = None
    change_type: Literal["added", "removed", "modified"]
    old: JsonValue = None
    new: JsonValue = None
    old_hash: str | None = None
    new_hash: str | None = None
    old_preview: str | None = None
    new_preview: str | None = None
    match_basis: str | None = None
    requires_review: bool = False


class ChangeDetail(ChangeSummary):
    from_id: ID
    to_id: ID
    from_analysis_id: ID | None
    to_analysis_id: ID | None
    from_revision_id: ID | None
    to_revision_id: ID | None
    changeset_version: str
    category_counts: dict[str, int]
    changed_fields: list[str]
    changes: list[ChangeRecord] = Field(max_length=2000)


class PipelineRequest(Response):
    source: SourceSlug


class PipelineTrigger(Response):
    run_id: ID
    source: str
    status: str
    celery_task_id: str
    reused: bool


class RunSummary(Response):
    id: ID
    source: str
    trigger: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stage_count: int


class StageSummary(Response):
    id: ID
    stage: str
    entity_type: str
    entity_id: int
    status: str
    attempt: int
    metrics: dict[str, int | bool]
    failure_reason: str | None


class RunDetail(RunSummary):
    summary: dict[str, int | bool]
    failure_reason: str | None
    stages: list[StageSummary] = Field(max_length=100)
    next_after_stage_id: int | None


class Dashboard(Response):
    active_tenders_count: int
    tender_count: int
    company_count: int
    upcoming_deadlines: list[TenderSummary] = Field(max_length=5)
    recent_changes: list[ChangeSummary] = Field(max_length=5)
    recent_runs: list[RunSummary] = Field(max_length=5)
