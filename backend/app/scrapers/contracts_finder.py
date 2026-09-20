import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.schemas.source import SourceCreate
from app.scrapers.errors import InvalidRecord, SourceFetchError, SourceParseError
from app.scrapers.records import ParsedListing, ScrapedTender

SOURCE = SourceCreate(
    name="Contracts Finder",
    slug="contracts-finder",
    base_url="https://www.contractsfinder.service.gov.uk",
)
SEARCH_URL = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
BATCH_LIMIT = 20
logger = logging.getLogger(__name__)


def fetch_releases(client: httpx.Client) -> object:
    logger.info("event=scraper_start source=%s", SOURCE.slug)
    try:
        response = client.get(
            SEARCH_URL,
            params={"stages": "tender", "limit": BATCH_LIMIT},
            headers={
                "User-Agent": "TenderScoutAI/0.1 (public procurement reader)",
                "Accept": "application/json",
            },
            timeout=30.0,
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
        raise SourceFetchError(
            "Contracts Finder request failed; see HTTP failure log"
        ) from None
    media_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type not in {"application/json", "text/json"}:
        raise SourceFetchError("Expected a Contracts Finder JSON response")
    try:
        return response.json()
    except ValueError:
        raise SourceParseError("Contracts Finder returned invalid JSON") from None


def object_value(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidRecord("Expected an OCDS object")
    return value


def object_list(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise InvalidRecord("Expected an array of OCDS objects")
    return value


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRecord("Expected text")
    return " ".join(value.split()) or None


def parse_date(value: object) -> datetime | None:
    value = clean_text(value)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidRecord("Invalid ISO datetime") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidRecord("Datetime must include a timezone offset")
    return parsed.astimezone(UTC)


def notice_identity(tender: dict) -> tuple[str, str]:
    notices = {}
    for document in object_list(tender.get("documents")):
        if (
            document.get("documentType") != "tenderNotice"
            or document.get("format") != "text/html"
        ):
            continue
        value = clean_text(document.get("url"))
        if not value:
            continue
        try:
            url = urlsplit(value)
        except ValueError:
            raise InvalidRecord("Malformed notice URL") from None
        if url.scheme != "https" or url.netloc not in {
            "www.contractsfinder.service.gov.uk",
            "contractsfinder.service.gov.uk",
        }:
            continue
        match = re.fullmatch(r"/Notice/([0-9a-fA-F-]{36})", url.path)
        if match:
            try:
                notice_id = str(UUID(match[1]))
            except ValueError:
                raise InvalidRecord("Malformed notice UUID") from None
            notices[notice_id] = value
    if len(notices) != 1:
        raise InvalidRecord("Expected one official HTML tender notice URL")
    return next(iter(notices.items()))


def buyer_name(release: dict) -> str | None:
    buyer = object_value(release.get("buyer"))
    name = clean_text(buyer.get("name"))
    if name:
        return name
    names = set()
    for party in object_list(release.get("parties")):
        roles = party.get("roles", [])
        if not isinstance(roles, list):
            raise InvalidRecord("Expected party roles array")
        if buyer.get("id"):
            is_buyer = party.get("id") == buyer["id"]
        else:
            is_buyer = "buyer" in roles
        name = clean_text(party.get("name")) if is_buyer else None
        if name:
            names.add(name)
    return "; ".join(sorted(names)) or None


def delivery_location(tender: dict) -> str | None:
    countries = set()
    for item in object_list(tender.get("items")):
        for address in object_list(item.get("deliveryAddresses")):
            country = clean_text(address.get("countryName"))
            if country:
                countries.add(country)
    return "; ".join(sorted(countries)) or None


def parse_release(value: object) -> ScrapedTender | None:
    release = object_value(value)
    tags = release.get("tag")
    if (
        not isinstance(tags, list)
        or not tags
        or any(not isinstance(tag, str) for tag in tags)
    ):
        raise InvalidRecord("Missing or malformed release tags")
    if not {"tender", "tenderUpdate", "tenderAmendment"}.intersection(tags):
        return None
    tender = object_value(release.get("tender"))
    status = clean_text(tender.get("status"))
    if status not in {
        "active",
        "planning",
        "planned",
        "complete",
        "cancelled",
        "unsuccessful",
        "withdrawn",
    }:
        raise InvalidRecord("Missing or unrecognized tender status")
    if status != "active":
        return None
    external_id, source_url = notice_identity(tender)
    period = object_value(tender.get("tenderPeriod"))
    return ScrapedTender(
        external_id=external_id,
        title=clean_text(tender.get("title")) or "",
        organization=buyer_name(release),
        description=clean_text(tender.get("description")),
        source_url=source_url,
        category=clean_text(tender.get("mainProcurementCategory")),
        location=delivery_location(tender),
        published_at=parse_date(tender.get("datePublished")),
        deadline=parse_date(period.get("endDate")),
    )


def parse_releases(payload: object) -> ParsedListing:
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), list):
        raise SourceParseError("Expected a Contracts Finder OCDS releases array")
    listing = ParsedListing()
    for position, release in enumerate(payload["releases"], start=1):
        try:
            record = parse_release(release)
        except (InvalidRecord, ValidationError) as error:
            listing.failed += 1
            reason = (
                str(error)
                if isinstance(error, InvalidRecord)
                else "Invalid normalized fields"
            )
            logger.warning(
                "event=record_rejected source=%s position=%d reason=%s",
                SOURCE.slug,
                position,
                reason,
            )
            continue
        if record is None:
            listing.skipped += 1
        else:
            listing.records.append(record)
    if listing.failed and not listing.records:
        raise SourceParseError(
            "No valid Contracts Finder tenders remain after parsing failures"
        )
    return listing
