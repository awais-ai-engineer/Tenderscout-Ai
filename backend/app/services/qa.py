import json
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.client import ProviderError, StructuredLLMClient
from app.ai.embeddings import EmbeddingClient
from app.models import DocumentVersion, TenderQuestion
from app.rag.chunking import CHUNKER_VERSION, text_hash
from app.rag.config import EmbeddingConfig
from app.rag.prompt import RAG_ANSWER_PROMPT, AnswerPrompt
from app.rag.schemas import TenderAnswerOutput
from app.services.analysis import DocumentVersionNotFound
from app.services.retrieval import (
    RETRIEVAL_VERSION,
    RetrievalError,
    RetrievedChunk,
    normalize_question,
    retrieve,
)

INSUFFICIENT_MESSAGE = "The answer is not established by the indexed tender text."


@dataclass(frozen=True)
class AnswerContext:
    text: str = field(repr=False)
    chunks: tuple[RetrievedChunk, ...] = field(repr=False)
    context_hash: str


def build_context(chunks: list[RetrievedChunk], max_chars: int) -> AnswerContext:
    if type(max_chars) is not int or not 256 <= max_chars <= 64000:
        raise ValueError("Context limit must be between 256 and 64000 characters")
    records, included = [], []
    context = "[]"
    for chunk in chunks:
        record = {
            "chunk_id": chunk.chunk_id,
            "document_version_id": chunk.document_version_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
        }
        candidate = json.dumps(
            [*records, record], ensure_ascii=False, separators=(",", ":")
        )
        if len(candidate) <= max_chars:
            records.append(record)
            included.append(chunk)
            context = candidate
    return AnswerContext(context, tuple(included), text_hash(context))


def validate_citations(
    output: TenderAnswerOutput, context: AnswerContext
) -> list[dict]:
    chunks = {chunk.chunk_id: chunk for chunk in context.chunks}
    citations = []
    seen = set()
    for citation in output.citations:
        chunk = chunks.get(citation.chunk_id)
        quote = " ".join(citation.quote.split())
        if chunk is None or not quote or quote not in " ".join(chunk.text.split()):
            raise ValueError("Citation is not grounded in its included source chunk")
        key = (citation.chunk_id, quote)
        if key not in seen:
            seen.add(key)
            citations.append(
                {
                    "document_version_id": chunk.document_version_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "quote": citation.quote,
                }
            )
    return citations


@dataclass(frozen=True)
class QuestionResult:
    question_id: int
    document_version_id: int
    status: str
    answer: str | None = field(repr=False)
    citations: list[dict] = field(repr=False)
    failure_reason: str | None
    reused: bool


def question_result(row: TenderQuestion, *, reused: bool) -> QuestionResult:
    return QuestionResult(
        row.id,
        row.document_version_id,
        row.status,
        row.answer,
        row.citations,
        row.failure_reason,
        reused,
    )


def persist_question(engine: Engine, identity: dict, values: dict) -> QuestionResult:
    query = select(TenderQuestion).filter_by(**identity)
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                select(DocumentVersion.id)
                .where(DocumentVersion.id == identity["document_version_id"])
                .with_for_update()
            ).scalar_one()
            existing = session.scalar(query)
            if existing is not None:
                return question_result(existing, reused=True)
            row = TenderQuestion(**identity, **values)
            session.add(row)
            session.flush()
            return question_result(row, reused=False)
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(query)
            if existing is not None:
                return question_result(existing, reused=True)
        raise


def generate_answer(
    client: StructuredLLMClient,
    model: str,
    question: str,
    context: AnswerContext,
    prompt: AnswerPrompt,
) -> tuple[str, str | None, list[dict], str | None]:
    if not context.chunks:
        return "insufficient", None, [], None
    text = json.dumps({"question": question}, ensure_ascii=False, separators=(",", ":"))
    text += "\nUNTRUSTED_TENDER_CONTEXT_JSON:\n" + context.text
    try:
        response = client.generate(
            model=model, instructions=prompt.instructions, text=text
        )
    except ProviderError as exc:
        return "failed", None, [], exc.reason.value
    except Exception:
        return "failed", None, [], "Answer provider request failed"
    try:
        if not isinstance(response, str) or len(response) > 30000:
            raise ValueError("Invalid response size or type")
        output = TenderAnswerOutput.model_validate_json(response)
        citations = validate_citations(output, context)
    except ValidationError:
        return "failed", None, [], "Answer output failed schema validation"
    except ValueError:
        return "failed", None, [], "Answer output or citations failed validation"
    return (
        "insufficient" if output.insufficient_evidence else "completed",
        output.answer,
        citations,
        None,
    )


def ask_tender(
    engine: Engine,
    document_version_id: int,
    question: str,
    embedding_client: EmbeddingClient,
    answer_client: StructuredLLMClient,
    *,
    embedding: EmbeddingConfig,
    answer_model: str,
    top_k: int = 5,
    max_context_chars: int = 12000,
    chunker_version: str = CHUNKER_VERSION,
    retrieval_version: str = RETRIEVAL_VERSION,
    prompt: AnswerPrompt = RAG_ANSWER_PROMPT,
) -> QuestionResult:
    question = normalize_question(question)
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    context = build_context([], max_context_chars)
    with Session(engine) as session:
        if session.get(DocumentVersion, document_version_id) is None:
            raise DocumentVersionNotFound("Document version does not exist")
    failure = None
    try:
        chunks = retrieve(
            engine,
            document_version_id,
            question,
            embedding_client,
            embedding=embedding,
            top_k=top_k,
            chunker_version=chunker_version,
        )
        if any(chunk.document_version_id != document_version_id for chunk in chunks):
            raise RetrievalError("Retrieval returned a different document version")
        context = build_context(chunks, max_context_chars)
    except ProviderError as exc:
        failure = exc.reason.value
    except RetrievalError as exc:
        failure = str(exc)
    identity = {
        "document_version_id": document_version_id,
        "question_hash": text_hash(question),
        "embedding_provider": embedding_client.provider,
        "embedding_model": embedding.model,
        "embedding_dimensions": embedding.dimensions,
        "answer_provider": answer_client.provider,
        "answer_model": answer_model,
        "chunker_version": chunker_version,
        "retrieval_version": retrieval_version,
        "answer_prompt_version": prompt.version,
        "top_k": top_k,
        "max_context_chars": max_context_chars,
        "context_hash": context.context_hash,
        "retrieval_succeeded": failure is None,
    }
    with Session(engine) as session:
        existing = session.scalar(select(TenderQuestion).filter_by(**identity))
        if existing is not None:
            return question_result(existing, reused=True)
    status, answer, citations, reason = (
        ("failed", None, [], failure)
        if failure is not None
        else generate_answer(answer_client, answer_model, question, context, prompt)
    )
    return persist_question(
        engine,
        identity,
        {
            "question": question,
            "context_chunk_ids": [chunk.chunk_id for chunk in context.chunks],
            "status": status,
            "answer": answer,
            "citations": citations,
            "failure_reason": reason,
        },
    )
