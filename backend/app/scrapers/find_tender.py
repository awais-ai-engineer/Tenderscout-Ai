import logging
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from app.schemas.source import SourceCreate
from app.scrapers.errors import (
    InvalidRecord,
    SourceFetchError,
    SourceParseError,
    TransientSourceFetchError,
)
from app.scrapers.records import ParsedListing, ScrapedTender

SOURCE = SourceCreate(
    name="Find a Tender",
    slug="find-a-tender",
    base_url="https://www.find-tender.service.gov.uk",
)
LISTING_URL = urljoin(str(SOURCE.base_url), "Search/Results")
USER_AGENT = "TenderScoutAI/0.1 (public tender listing reader)"
UK_TIMEZONE = ZoneInfo("Europe/London")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
logger = logging.getLogger(__name__)


def fetch_listing(client: httpx.Client, *, timeout: float = 20.0) -> str:
    logger.info("event=scraper_start source=%s", SOURCE.slug)
    headers = {"User-Agent": USER_AGENT}
    try:
        robots = client.get(
            urljoin(str(SOURCE.base_url), "robots.txt"),
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
        )
        if robots.status_code != 404:
            robots.raise_for_status()
            rules = RobotFileParser()
            rules.parse(robots.text.splitlines())
            if not rules.can_fetch(USER_AGENT, LISTING_URL):
                raise SourceFetchError("Listing access is disallowed by robots.txt")
        response = client.get(
            LISTING_URL, timeout=timeout, headers=headers, follow_redirects=False
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
        raise failure("Public source request failed; see HTTP failure log") from None
    if "text/html" not in response.headers.get("content-type", "").lower():
        raise SourceFetchError("Expected an HTML listing response")
    return response.text


def text_value(element: Tag | None) -> str | None:
    if element is None:
        return None
    return " ".join(element.get_text(" ", strip=True).split()) or None


def parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    match = re.fullmatch(
        r"(\d{1,2}) ([A-Za-z]+) (\d{4}), (\d{1,2}):(\d{2})(am|pm)", value
    )
    if not match:
        raise InvalidRecord("Unrecognized date format")
    day, month, year, hour, minute, period = match.groups()
    try:
        if not 1 <= int(hour) <= 12:
            raise ValueError("Invalid hour")
        local = datetime(
            int(year),
            MONTHS.index(month) + 1,
            int(day),
            int(hour) % 12 + (12 if period == "pm" else 0),
            int(minute),
            tzinfo=UK_TIMEZONE,
        )
    except ValueError as error:
        raise InvalidRecord("Invalid calendar date or time") from error
    if local.utcoffset() != local.replace(fold=1).utcoffset():
        raise InvalidRecord("Ambiguous or nonexistent UK local time")
    return local.astimezone(UTC)


def notice_url(href: str) -> tuple[str, str]:
    try:
        url = urlsplit(urljoin(LISTING_URL, href))
    except ValueError as error:
        raise InvalidRecord("Malformed notice URL") from error
    match = re.fullmatch(r"/Notice/(\d{6}-\d{4})/?", url.path)
    if (
        url.scheme != "https"
        or url.netloc != "www.find-tender.service.gov.uk"
        or match is None
    ):
        raise InvalidRecord("Expected a public Find a Tender notice URL")
    external_id = match[1]
    return external_id, urljoin(str(SOURCE.base_url), f"Notice/{external_id}")


def parse_record(row: Tag) -> ScrapedTender | None:
    fields = {}
    for label in row.select("dl dt"):
        fields[text_value(label)] = text_value(label.find_next_sibling("dd"))
    notice_type = fields.get("Notice type")
    if not notice_type or not re.fullmatch(r"(?:UK|F)\d+: .+", notice_type):
        raise InvalidRecord("Missing or unrecognized notice type")
    if notice_type != "UK4: Tender notice":
        if notice_type.startswith("UK4:"):
            raise InvalidRecord("UK4 notice label changed")
        return None
    heading = row.find("h2")
    link = heading.find("a", href=True) if heading is not None else None
    if link is None:
        raise InvalidRecord("Missing tender title link")
    external_id, source_url = notice_url(str(link["href"]))
    description_id = heading.get("aria-describedby")
    description = row.find(id=description_id) if description_id else None
    location = fields.get("Contract location") or fields.get("Contract locations")
    return ScrapedTender(
        external_id=external_id,
        title=text_value(link) or "",
        organization=text_value(row.select_one(".search-result-sub-header")),
        description=text_value(description),
        source_url=source_url,
        location=None if location == "Location not specified" else location,
        published_at=parse_date(fields.get("Publication date")),
        deadline=parse_date(fields.get("Submission deadline")),
    )


def parse_listing(html: str) -> ParsedListing:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#dashboard_notices")
    count = text_value(soup.select_one(".search-result-count"))
    if container is None or count is None or not re.fullmatch(r"\d+(?:,\d{3})*", count):
        raise SourceParseError("Find a Tender results container or count is missing")
    rows = container.select(".search-result")
    total = int(count.replace(",", ""))
    if (total > 0 and not rows) or len(rows) > total:
        raise SourceParseError("Notice count and result structure do not agree")
    parsed = ParsedListing()
    for position, row in enumerate(rows, start=1):
        try:
            record = parse_record(row)
        except (InvalidRecord, ValidationError) as error:
            parsed.failed += 1
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
            parsed.skipped += 1
        else:
            parsed.records.append(record)
    if parsed.failed and not parsed.records:
        raise SourceParseError("No valid tender records remain after parsing failures")
    return parsed
