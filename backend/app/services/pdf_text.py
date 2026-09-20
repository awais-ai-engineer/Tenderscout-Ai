import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pypdf import PdfReader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    status: Literal["extracted", "empty", "failed"]
    text: str | None = None
    error: str | None = None


def extract_pdf(path: Path, max_pages: int) -> ExtractionResult:
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                return ExtractionResult(
                    "failed", error="Encrypted PDFs are unsupported"
                )
            if len(reader.pages) > max_pages:
                return ExtractionResult("failed", error="PDF exceeds page limit")
            pages = [
                (page.extract_text() or "").replace("\x00", "").strip()
                for page in reader.pages
            ]
            text = "\n\n".join(pages).strip()
            return (
                ExtractionResult("extracted", text)
                if text
                else ExtractionResult("empty")
            )
    except Exception as exc:
        # Malformed PDFs can raise outside pypdf's exception hierarchy. Keep the
        # raw version for any parser failure, but let process interrupts propagate.
        logger.warning("PDF extraction failed (%s)", type(exc).__name__)
        return ExtractionResult(
            "failed", error=f"PDF extraction failed ({type(exc).__name__})"
        )
