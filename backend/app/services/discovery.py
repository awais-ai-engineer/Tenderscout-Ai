"""Bounded live refresh followed by a relevance-ordered stored tender read."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.product import SourceSlug
from app.scrapers import contracts_finder, find_tender
from app.scrapers.records import ParsedListing
from app.services import ingestion, queries

logger = logging.getLogger(__name__)
SOURCES = {
    contracts_finder.SOURCE.slug: contracts_finder.SOURCE,
    find_tender.SOURCE.slug: find_tender.SOURCE,
}
MAX_RESULTS_PER_SOURCE = 20
LIVE_REQUEST_TIMEOUT_SECONDS = 8.0


class InvalidQuery(ValueError):
    pass


class LiveSearchUnavailable(RuntimeError):
    pass


def normalize_query(value: str | None) -> str:
    if value is None or not value.strip():
        return ""
    normalized = " ".join(value.split())
    if not 3 <= len(normalized) <= 255:
        raise InvalidQuery("Search must contain 3 to 255 characters")
    return normalized


def fetch_source(slug: SourceSlug) -> tuple[ParsedListing, datetime]:
    """Read one public, bounded batch; neither source has verified text search here."""
    with httpx.Client() as client:
        if slug == contracts_finder.SOURCE.slug:
            listing = contracts_finder.parse_releases(
                contracts_finder.fetch_releases(
                    client, timeout=LIVE_REQUEST_TIMEOUT_SECONDS
                )
            )
        else:
            listing = find_tender.parse_listing(
                find_tender.fetch_listing(client, timeout=LIVE_REQUEST_TIMEOUT_SECONDS)
            )
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    records = []
    for record in listing.records:
        url = str(record.source_url)
        if url in seen_urls or (record.external_id and record.external_id in seen_ids):
            continue
        seen_urls.add(url)
        if record.external_id:
            seen_ids.add(record.external_id)
        records.append(record)
        if len(records) == MAX_RESULTS_PER_SOURCE:
            break
    return ParsedListing(
        records=records, failed=listing.failed, skipped=listing.skipped
    ), datetime.now(UTC)


def search(
    engine,
    *,
    q: str | None,
    source: SourceSlug | None = None,
    organization: str | None = None,
    category: str | None = None,
    deadline_before=None,
    limit: int = 20,
    cursor: int | None = None,
) -> dict:
    requested_at = datetime.now(UTC)
    term = normalize_query(q)
    if term and cursor is not None:
        raise InvalidQuery("Cursor is only available for recorded browsing")
    if not term:
        recorded = queries.tenders(
            engine,
            cursor=cursor,
            limit=limit,
            source=source,
            organization=organization,
            category=category,
            deadline_before=deadline_before,
        )
        return {
            **recorded,
            "items": [dict(item, freshly_fetched=False) for item in recorded["items"]],
            "requested_at": requested_at,
            "mode": "recorded",
            "sources": [],
            "result_count": len(recorded["items"]),
        }

    selected = [source] if source else list(SOURCES)
    fetched: dict[str, tuple[ParsedListing, datetime]] = {}
    statuses = {}
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {executor.submit(fetch_source, slug): slug for slug in selected}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                fetched[slug] = future.result()
            except Exception as exc:
                logger.warning(
                    "event=live_source_unavailable source=%s error=%s",
                    slug,
                    type(exc).__name__,
                )
                statuses[slug] = {
                    "source": slug,
                    "status": "unavailable",
                    "error_code": "source_unavailable",
                }

    fresh_ids: set[int] = set()
    for slug in selected:
        if slug not in fetched:
            continue
        listing, fetched_at = fetched[slug]
        affected: set[int] = set()
        try:
            ingestion.ingest_tenders(
                engine, SOURCES[slug], listing, affected_ids=affected
            )
        except (SQLAlchemyError, ingestion.InactiveSourceError) as exc:
            logger.warning(
                "event=live_persistence_unavailable source=%s error=%s",
                slug,
                type(exc).__name__,
            )
            statuses[slug] = {
                "source": slug,
                "status": "unavailable",
                "error_code": "source_unavailable",
            }
        else:
            fresh_ids.update(affected)
            statuses[slug] = {
                "source": slug,
                "status": "success",
                "fetched_at": fetched_at,
            }

    try:
        rows = queries.discover_tenders(
            engine,
            search=term,
            limit=limit,
            source=source,
            organization=organization,
            category=category,
            deadline_before=deadline_before,
        )
    except SQLAlchemyError:
        if all(statuses[slug]["status"] == "unavailable" for slug in selected):
            raise LiveSearchUnavailable from None
        raise
    return {
        "items": [dict(row, freshly_fetched=row["id"] in fresh_ids) for row in rows],
        "next_cursor": None,
        "requested_at": requested_at,
        "mode": "live",
        "sources": [statuses[slug] for slug in selected],
        "result_count": len(rows),
    }
