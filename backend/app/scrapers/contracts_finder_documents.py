import logging

from pydantic import ValidationError

from app.scrapers.contracts_finder import (
    clean_text,
    notice_identity,
    object_list,
    object_value,
)
from app.scrapers.errors import InvalidRecord, SourceParseError
from app.scrapers.records import DiscoveredDocument, DiscoveredDocuments

logger = logging.getLogger(__name__)


def discover_documents(payload: object) -> DiscoveredDocuments:
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), list):
        raise SourceParseError("Expected an OCDS releases list")
    result = DiscoveredDocuments()
    for release in payload["releases"]:
        try:
            tender = object_value(object_value(release).get("tender"))
            documents = object_list(tender.get("documents"))
            if not documents:
                continue
            external_id, notice_url = notice_identity(tender)
        except InvalidRecord:
            result.failed += 1
            logger.warning("Cannot resolve document parent from OCDS release")
            continue
        for document in documents:
            try:
                if clean_text(document.get("url")) == notice_url:
                    continue
                result.records.append(
                    DiscoveredDocument(
                        tender_external_id=external_id,
                        source_document_id=clean_text(document.get("id")),
                        title=clean_text(document.get("title")),
                        source_url=document.get("url"),
                        document_type=clean_text(document.get("documentType")),
                        media_type=clean_text(document.get("format")),
                    )
                )
            except (InvalidRecord, ValidationError):
                result.failed += 1
                logger.warning("Invalid Contracts Finder document metadata")
    return result
