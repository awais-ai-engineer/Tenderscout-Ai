import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, StructuredLLMClient
from app.ai.prompt import TENDER_ANALYSIS_PROMPT, AnalysisPrompt
from app.ai.schemas import ANALYSIS_SCHEMA_VERSION, TenderAnalysisOutput
from app.models import DocumentVersion, TenderAnalysis

logger = logging.getLogger(__name__)
TRUNCATION_MARKER = "\n\n... [TRUNCATED BY TENDERSCOUT] ...\n\n"
MAX_RAW_RESPONSE_CHARS = 100000


class DocumentVersionNotFound(ValueError):
    pass


@dataclass(frozen=True)
class PreparedInput:
    text: str = field(repr=False)
    source_parts: tuple[str, ...] = field(repr=False)
    input_hash: str
    truncated: bool


@dataclass(frozen=True)
class AnalysisIdentity:
    document_version_id: int
    analysis_schema_version: str
    provider: str
    model: str
    prompt_version: str
    input_hash: str


@dataclass(frozen=True)
class AnalysisResult:
    document_version_id: int
    status: Literal["completed", "failed", "skipped"]
    analysis_id: int | None
    model: str
    reused: bool


def prepare_text(text: str, max_chars: int) -> PreparedInput:
    if max_chars < 128:
        raise ValueError("AI input limit must be at least 128 characters")
    normalized = (
        text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    )
    truncated = len(normalized) > max_chars
    if truncated:
        remaining = max_chars - len(TRUNCATION_MARKER)
        head_size = (remaining + 1) // 2
        tail_size = remaining // 2
        parts = (normalized[:head_size], normalized[-tail_size:])
        prepared = TRUNCATION_MARKER.join(parts)
    else:
        prepared = normalized
        parts = (normalized,)
    return PreparedInput(
        prepared, parts, hashlib.sha256(prepared.encode("utf-8")).hexdigest(), truncated
    )


def prepare_document(
    engine: Engine, document_version_id: int, max_chars: int
) -> PreparedInput | None:
    with Session(engine) as session:
        version = session.get(DocumentVersion, document_version_id)
        if version is None:
            raise DocumentVersionNotFound("Document version does not exist")
        if version.extraction_status != "extracted" or not version.extracted_text:
            return None
        prepared = prepare_text(version.extracted_text, max_chars)
    return prepared if prepared.text else None


def check_evidence(output: TenderAnalysisOutput, prepared: PreparedInput) -> None:
    source_parts = [" ".join(part.split()) for part in prepared.source_parts]
    for evidence in output.evidence_snippets():
        snippet = " ".join(evidence.split())
        if not any(snippet in source for source in source_parts):
            raise ValueError("Evidence not found in the prepared source text")


def existing_analysis(
    session: Session, identity: AnalysisIdentity
) -> TenderAnalysis | None:
    return session.scalar(select(TenderAnalysis).filter_by(**asdict(identity)))


def response_for_storage(response: str) -> str:
    # PostgreSQL text/JSONB cannot store NULs or unpaired Unicode surrogates.
    bounded = response[:MAX_RAW_RESPONSE_CHARS]
    escaped = bounded.encode("utf-8", errors="backslashreplace").decode("utf-8")
    return escaped.replace("\x00", "\\u0000")[:MAX_RAW_RESPONSE_CHARS]


def result_for(row: TenderAnalysis, *, reused: bool) -> AnalysisResult:
    return AnalysisResult(
        row.document_version_id, row.status, row.id, row.model, reused
    )


def persist_analysis(
    engine: Engine,
    identity: AnalysisIdentity,
    raw_response: str | None,
    output: TenderAnalysisOutput | None,
    failure_reason: str | None,
) -> AnalysisResult:
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                select(DocumentVersion.id)
                .where(DocumentVersion.id == identity.document_version_id)
                .with_for_update()
            ).scalar_one()
            existing = existing_analysis(session, identity)
            if existing is not None:
                return result_for(existing, reused=True)
            row = TenderAnalysis(
                **asdict(identity),
                status="completed" if output is not None else "failed",
                raw_response=raw_response,
                failure_reason=failure_reason,
                **(output.model_dump(mode="json") if output is not None else {}),
            )
            session.add(row)
            session.flush()
            return result_for(row, reused=False)
    except IntegrityError:
        # Also tolerate a writer that relies only on the unique constraint.
        with Session(engine) as session:
            existing = existing_analysis(session, identity)
            if existing is not None:
                return result_for(existing, reused=True)
        raise


def analyze_document(
    engine: Engine,
    document_version_id: int,
    client: StructuredLLMClient,
    *,
    model: str,
    max_input_chars: int,
    prompt: AnalysisPrompt = TENDER_ANALYSIS_PROMPT,
    schema_version: str = ANALYSIS_SCHEMA_VERSION,
) -> AnalysisResult:
    prepared = prepare_document(engine, document_version_id, max_input_chars)
    if prepared is None:
        return AnalysisResult(document_version_id, "skipped", None, model, False)
    identity = AnalysisIdentity(
        document_version_id,
        schema_version,
        client.provider,
        model,
        prompt.version,
        prepared.input_hash,
    )
    with Session(engine) as session:
        existing = existing_analysis(session, identity)
        if existing is not None:
            return result_for(existing, reused=True)

    raw_response = None
    output = None
    failure_reason = None
    try:
        response = client.generate(
            model=model, instructions=prompt.instructions, text=prepared.text
        )
    except ProviderError as exc:
        failure_reason = exc.reason.value
    except Exception:
        # This boundary must not leak SDK/transport details or discard the failure.
        failure_reason = "Provider call failed unexpectedly"
    else:
        if not isinstance(response, str):
            failure_reason = "Provider output is not JSON text"
        elif len(response) > MAX_RAW_RESPONSE_CHARS:
            raw_response = response_for_storage(response)
            failure_reason = (
                "Provider output exceeds storage limit; raw response truncated"
            )
        else:
            raw_response = response_for_storage(response)
            try:
                validated = TenderAnalysisOutput.model_validate_json(response)
                check_evidence(validated, prepared)
                output = validated
                raw_response = json.dumps(
                    json.loads(response), ensure_ascii=False, separators=(",", ":")
                )
            except ValidationError:
                failure_reason = "Provider output failed schema validation"
            except ValueError:
                failure_reason = "Evidence not found in the prepared source text"
    if failure_reason:
        logger.warning("Tender analysis failed: %s", failure_reason)
    return persist_analysis(engine, identity, raw_response, output, failure_reason)
