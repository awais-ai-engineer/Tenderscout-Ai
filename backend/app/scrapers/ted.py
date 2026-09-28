"""Official TED v3 Search API adapter."""

import logging
import re
from datetime import UTC, date, datetime, timedelta

import httpx
from pydantic import ValidationError

from app.schemas.source import SourceCreate
from app.scrapers.errors import (
    InvalidRecord,
    SourceFetchError,
    SourceParseError,
    TransientSourceFetchError,
)
from app.scrapers.records import ParsedListing, ScrapedTender

SOURCE = SourceCreate(name="TED", slug="ted", base_url="https://ted.europa.eu")
SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
USER_AGENT = "TenderScoutAI/0.1 (public procurement reader)"
FIELDS = (
    "publication-number",
    "notice-title",
    "description-proc",
    "buyer-name",
    "classification-cpv",
    "buyer-country",
    "publication-date",
    "deadline-receipt-tender-date-lot",
)
logger = logging.getLogger(__name__)


def expert_text_query(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    return f'FT~"{escaped}" SORT BY publication-date DESC'


def fetch_notices(
    client: httpx.Client, *, query: str, limit: int, timeout: float
) -> object:
    if not 1 <= limit <= 100:
        raise ValueError("TED limit must be between 1 and 100")
    try:
        response = client.post(
            SEARCH_URL,
            json={
                "query": query,
                "fields": list(FIELDS),
                "page": 1,
                "limit": limit,
                "scope": "ACTIVE",
                "checkQuerySyntax": True,
                "paginationMode": "PAGE_NUMBER",
                "onlyLatestVersions": True,
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=False,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        status = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else None
        )
        logger.error(
            "event=source_http_failure source=%s error=%s status=%s",
            SOURCE.slug,
            type(error).__name__,
            status,
        )
        failure = (
            TransientSourceFetchError
            if isinstance(error, (httpx.TimeoutException, httpx.ConnectError))
            else SourceFetchError
        )
        raise failure("TED request failed; see HTTP failure log") from None
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise SourceFetchError("Expected a TED JSON response")
    try:
        return response.json()
    except ValueError:
        raise SourceParseError("TED returned invalid JSON") from None


def _values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if isinstance(value, dict):
        preferred = value.get("eng") or value.get("mul")
        if preferred is not None:
            return _values(preferred)
        for item in value.values():
            values = _values(item)
            if values:
                return values
    raise InvalidRecord("Expected TED text or multilingual text")


def _text(value: object, *, maximum: int | None = None) -> str | None:
    result = "; ".join(dict.fromkeys(" ".join(item.split()) for item in _values(value)))
    if not result:
        return None
    return result[:maximum] if maximum else result


def _date(value: object) -> datetime | None:
    values = _values(value)
    if not values:
        return None
    try:
        parsed = min(date.fromisoformat(item) for item in values)
    except ValueError:
        raise InvalidRecord("Invalid TED date") from None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def parse_notice(value: object) -> ScrapedTender:
    if not isinstance(value, dict):
        raise InvalidRecord("Expected a TED notice object")
    external_id = _text(value.get("publication-number"), maximum=255)
    if external_id is None or not re.fullmatch(r"\d{6}-\d{4}", external_id):
        raise InvalidRecord("Missing or malformed TED publication number")
    title = _text(value.get("notice-title"))
    if not title:
        raise InvalidRecord("Missing TED notice title")
    return ScrapedTender(
        external_id=external_id,
        title=title,
        description=_text(value.get("description-proc")),
        organization=_text(value.get("buyer-name"), maximum=255),
        category=_text(value.get("classification-cpv"), maximum=255),
        location=_text(value.get("buyer-country"), maximum=255),
        published_at=_date(value.get("publication-date")),
        deadline=_date(value.get("deadline-receipt-tender-date-lot")),
        source_url=f"https://ted.europa.eu/en/notice/-/detail/{external_id}",
    )


def parse_notices(payload: object) -> ParsedListing:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("notices"), list)
        or not isinstance(payload.get("timedOut"), bool)
    ):
        raise SourceParseError("Expected a TED notices response")
    if payload["timedOut"]:
        raise SourceFetchError("TED search timed out")
    listing = ParsedListing()
    for position, notice in enumerate(payload["notices"], start=1):
        try:
            listing.records.append(parse_notice(notice))
        except (InvalidRecord, ValidationError) as error:
            listing.failed += 1
            logger.warning(
                "event=record_rejected source=%s position=%d reason=%s",
                SOURCE.slug,
                position,
                str(error) if isinstance(error, InvalidRecord) else "Invalid fields",
            )
    if listing.failed and not listing.records:
        raise SourceParseError("No valid TED tenders remain after parsing failures")
    return listing


def search(
    client: httpx.Client, *, query: str, limit: int, timeout: float
) -> ParsedListing:
    return parse_notices(
        fetch_notices(
            client, query=expert_text_query(query), limit=limit, timeout=timeout
        )
    )


def refresh(client: httpx.Client, *, limit: int, timeout: float) -> ParsedListing:
    since = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y%m%d")
    query = f"publication-date >= {since} SORT BY publication-date DESC"
    return parse_notices(
        fetch_notices(client, query=query, limit=limit, timeout=timeout)
    )
