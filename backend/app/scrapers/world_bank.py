"""World Bank's public project procurement notices API."""

import logging
import re
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from app.schemas.source import SourceCreate
from app.scrapers.errors import InvalidRecord, SourceFetchError, SourceParseError
from app.scrapers.records import ParsedListing, ScrapedTender

SOURCE = SourceCreate(
    name="World Bank", slug="world-bank", base_url="https://projects.worldbank.org"
)
API_URL = "https://search.worldbank.org/api/v2/procnotices"
FIELDS = (
    "id,notice_type,noticedate,notice_status,submission_deadline_date,"
    "project_ctry_name,project_name,bid_description,procurement_group,"
    "contact_organization"
)
NOTICE_TYPES = (
    "Invitation for Bids^"
    "Invitation for Prequalification^"
    "Request for Expression of Interest"
)
logger = logging.getLogger(__name__)


def _date(value: object) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise InvalidRecord("Invalid World Bank date")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%d-%b-%Y").replace(tzinfo=UTC)
        except ValueError:
            raise InvalidRecord("Invalid World Bank date") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_notice(value: object) -> ScrapedTender:
    if not isinstance(value, dict):
        raise InvalidRecord("Expected notice object")
    identifier = value.get("id")
    if not isinstance(identifier, str) or not re.fullmatch(r"OP\d{8}", identifier):
        raise InvalidRecord("Invalid World Bank notice ID")
    if value.get("notice_status") != "Published" or value.get(
        "notice_type"
    ) not in NOTICE_TYPES.split("^"):
        raise InvalidRecord("Notice is not an active procurement opportunity")
    title = value.get("bid_description")
    if not isinstance(title, str) or not title.strip():
        raise InvalidRecord("Missing World Bank bid description")
    try:
        return ScrapedTender(
            external_id=identifier,
            title=title.strip(),
            description=title.strip(),
            organization=value.get("contact_organization") or None,
            category=value.get("procurement_group") or None,
            location=value.get("project_ctry_name") or None,
            published_at=_date(value.get("noticedate")),
            deadline=_date(value.get("submission_deadline_date")),
            source_url=f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{identifier}",
        )
    except ValidationError:
        raise InvalidRecord("Malformed World Bank notice") from None


def fetch(
    client: httpx.Client, *, limit: int, timeout: float, query: str | None = None
) -> ParsedListing:
    if not 1 <= limit <= 100:
        raise ValueError("World Bank limit must be between 1 and 100")
    params = {
        "format": "json",
        "rows": limit,
        "os": 0,
        "fl": FIELDS,
        "srt": "noticedate",
        "order": "desc",
        "notice_type_exact": NOTICE_TYPES,
        "deadline_strdate": datetime.now(UTC).date().isoformat(),
    }
    if query:
        params["qterm"] = query
    try:
        response = client.get(
            API_URL, params=params, timeout=timeout, follow_redirects=False
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.warning(
            "event=source_http_failure source=world-bank error=%s", type(error).__name__
        )
        raise SourceFetchError("World Bank request failed") from None
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise SourceFetchError("Expected a World Bank JSON response")
    try:
        payload = response.json()
    except ValueError:
        raise SourceParseError("World Bank returned invalid JSON") from None
    if not isinstance(payload, dict) or not isinstance(
        payload.get("procnotices"), list
    ):
        raise SourceParseError("World Bank response shape changed")
    listing = ParsedListing()
    for item in payload["procnotices"][:limit]:
        try:
            listing.records.append(parse_notice(item))
        except InvalidRecord:
            listing.skipped += 1
    return listing
