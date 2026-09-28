"""Bounded live refresh followed by a relevance-ordered stored tender read."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.product import SourceSlug
from app.scrapers.records import ParsedListing
from app.services import ingestion, queries
from app.sources import SOURCE_CONNECTORS, connector

logger = logging.getLogger(__name__)
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


def search_source(slug: SourceSlug, query: str) -> tuple[ParsedListing, datetime]:
    source = connector(slug)
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        listing = source.search(
            client,
            query,
            limit=MAX_RESULTS_PER_SOURCE,
            timeout=LIVE_REQUEST_TIMEOUT_SECONDS,
        )
    return listing, datetime.now(UTC)


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

    selected = [source] if source else list(SOURCE_CONNECTORS)
    fetched: dict[str, tuple[ParsedListing, datetime]] = {}
    statuses = {}
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {
            executor.submit(search_source, slug, term): slug for slug in selected
        }
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
                engine, connector(slug).source, listing, affected_ids=affected
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
