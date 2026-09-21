from dataclasses import dataclass
from datetime import UTC, date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.schemas import ANALYSIS_SCHEMA_VERSION, EvidenceItem, TenderAnalysisOutput
from app.models import TenderAnalysis, TenderMatch
from app.schemas.company import CompanyInput
from app.services.companies import load_company
from app.services.matching_rules import alignment, hard_comparison, result

MATCHER_VERSION = "v1"


def compute_match(
    profile: CompanyInput, analysis: TenderAnalysisOutput, as_of: date
) -> dict:
    items = [
        hard_comparison(item, profile, as_of)
        for item in analysis.eligibility_requirements + analysis.financial_requirements
    ]
    for item in analysis.technical_requirements:
        comparison = hard_comparison(item, profile, as_of)
        items.append(
            comparison
            if comparison["company_fact"] is not None
            else alignment(item, profile)
        )
    items.extend(
        result(
            item,
            reason="No company document inventory is available.",
            category="document",
        )
        for item in analysis.required_documents
    )
    items.extend(
        result(
            item,
            reason="Submission compliance needs human review.",
            category="submission",
        )
        for item in analysis.submission_instructions
    )
    items.extend(
        result(
            EvidenceItem(value=item.criterion, evidence=item.evidence),
            reason="Evaluation criteria are not assessed by this matcher.",
            hard=False,
            category="evaluation",
        )
        for item in analysis.evaluation_criteria
    )
    hard = [item for item in items if item["hard_requirement"]]
    blockers = [item for item in hard if item["status"] == "unmatched"]
    eligibility = (
        "ineligible"
        if blockers
        else (
            "eligible"
            if hard and all(item["status"] == "matched" for item in hard)
            else "uncertain"
        )
    )
    comparable = [item for item in items if item["status"] != "unknown"]
    soft = [item for item in comparable if not item["hard_requirement"]]
    score = (
        None
        if not soft
        else int(
            (
                Decimal(100)
                * sum(item["status"] == "matched" for item in soft)
                / len(soft)
            ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    )
    coverage = (
        Decimal(len(comparable)) / len(items) if items else Decimal(0)
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    risks = [
        {"kind": "tender", "reason": item.value, "tender_evidence": item.evidence}
        for item in analysis.risks_or_ambiguities
    ]
    risks.append(
        {
            "kind": "review",
            "reason": "Company facts and completeness are user assertions, "
            "not independently verified. "
            "Review document requirements, dates, scope and eligibility before acting. "
            "Lexical alignment is not proof of compliance; "
            "no bid/no-bid decision is made.",
            "tender_evidence": None,
        }
    )
    risks.append(
        {
            "kind": "review",
            "reason": f"Certification validity uses analysis date {as_of}, not today. "
            "Holding a certification does not establish validity "
            "or document possession.",
            "tender_evidence": None,
        }
    )
    return {
        "eligibility_status": eligibility,
        "score": score,
        "coverage_ratio": coverage,
        "company_snapshot": profile.model_dump(mode="json"),
        "hard_blockers": blockers,
        "matched_requirements": [item for item in items if item["status"] == "matched"],
        "unmatched_requirements": [
            item for item in items if item["status"] == "unmatched"
        ],
        "unknown_requirements": [item for item in items if item["status"] == "unknown"],
        "capability_matches": [
            item for item in items if item["category"] == "capability"
        ],
        "certification_matches": [
            item for item in items if item["category"] == "certification"
        ],
        "experience_matches": [
            item for item in items if item["category"] == "experience"
        ],
        "risks": risks,
    }


@dataclass(frozen=True)
class MatchResult:
    match_id: int
    eligibility_status: str
    score: int | None
    coverage_ratio: Decimal
    hard_blockers: int
    matched: int
    unmatched: int
    unknown: int
    reused: bool

    @classmethod
    def from_row(cls, row: TenderMatch, *, reused: bool) -> "MatchResult":
        return cls(
            row.id,
            row.eligibility_status,
            row.score,
            row.coverage_ratio,
            len(row.hard_blockers),
            len(row.matched_requirements),
            len(row.unmatched_requirements),
            len(row.unknown_requirements),
            reused,
        )


def match_tender(engine: Engine, company_id: int, analysis_id: int) -> MatchResult:
    identity = (company_id, analysis_id, MATCHER_VERSION)
    query = select(TenderMatch).where(
        TenderMatch.company_id == identity[0],
        TenderMatch.tender_analysis_id == identity[1],
        TenderMatch.matcher_version == identity[2],
    )
    with Session(engine) as session:
        existing = session.scalar(query)
        if existing is not None:
            return MatchResult.from_row(existing, reused=True)
        profile = load_company(session, company_id)
        row = session.get(TenderAnalysis, analysis_id)
        if row is None or row.status != "completed":
            raise ValueError("A completed analysis is required")
        if row.analysis_schema_version != ANALYSIS_SCHEMA_VERSION:
            raise ValueError("Unsupported analysis schema version")
        analysis = TenderAnalysisOutput.model_validate(
            {field: getattr(row, field) for field in TenderAnalysisOutput.model_fields}
        )
        created_at = row.created_at
        as_of = (
            created_at.astimezone(UTC).date()
            if created_at.tzinfo is not None
            else created_at.date()
        )
    values = compute_match(profile, analysis, as_of)
    try:
        with Session(engine) as session, session.begin():
            existing = session.scalar(query)
            if existing is not None:
                return MatchResult.from_row(existing, reused=True)
            match = TenderMatch(
                company_id=identity[0],
                tender_analysis_id=identity[1],
                matcher_version=identity[2],
                **values,
            )
            session.add(match)
            session.flush()
            return MatchResult.from_row(match, reused=False)
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(query)
            if existing is None:
                raise
            return MatchResult.from_row(existing, reused=True)
