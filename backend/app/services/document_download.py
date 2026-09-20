import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.scrapers.records import DiscoveredDocument

ALLOWED_HOST = "www.contractsfinder.service.gov.uk"


class DocumentDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedDocument:
    content_hash: str
    byte_size: int
    media_type: str
    storage_path: str
    downloaded_at: datetime


def allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname == ALLOWED_HOST
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
        )
    except ValueError:
        return False


def supported_pdf(document: DiscoveredDocument) -> bool:
    # Discovery must explicitly identify a PDF; file suffixes are not evidence.
    return document.media_type == "application/pdf" and allowed_url(
        str(document.source_url)
    )


def download_pdf(
    client: httpx.Client, url: str, storage_dir: Path, max_bytes: int
) -> DownloadedDocument:
    if not allowed_url(url):
        raise DocumentDownloadError("Document URL is not allowed")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    temporary: Path | None = None
    try:
        with client.stream(
            "GET",
            url,
            headers={
                "User-Agent": "TenderScoutAI/0.1 (public procurement document reader)",
                "Accept": "application/pdf, application/octet-stream",
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            auth=None,
        ) as response:
            response.raise_for_status()
            media_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media_type not in {"application/pdf", "application/octet-stream"}:
                raise DocumentDownloadError("Response is not a PDF media type")
            if (
                response.headers.get("content-encoding", "identity").lower()
                != "identity"
            ):
                raise DocumentDownloadError(
                    "Encoded document responses are unsupported"
                )
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    raise DocumentDownloadError("Invalid Content-Length") from None
                if size < 0 or size > max_bytes:
                    raise DocumentDownloadError("Content-Length exceeds document limit")
            storage_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            byte_size = 0
            prefix = b""
            with tempfile.NamedTemporaryFile(
                dir=storage_dir, suffix=".part", delete=False
            ) as output:
                temporary = Path(output.name)
                for chunk in response.iter_bytes(chunk_size=65536):
                    byte_size += len(chunk)
                    if byte_size > max_bytes:
                        raise DocumentDownloadError(
                            "Stream exceeds document byte limit"
                        )
                    if len(prefix) < 5:
                        prefix = (prefix + chunk)[:5]
                    digest.update(chunk)
                    output.write(chunk)
                if prefix != b"%PDF-":
                    raise DocumentDownloadError("Missing PDF signature")
                output.flush()
                os.fsync(output.fileno())
            content_hash = digest.hexdigest()
            relative = Path(content_hash[:2]) / f"{content_hash}.pdf"
            target = storage_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # Concurrent identical downloads produce the same immutable bytes.
            if not target.exists():
                os.replace(temporary, target)
            return DownloadedDocument(
                content_hash,
                byte_size,
                media_type,
                relative.as_posix(),
                datetime.now(UTC),
            )
    except httpx.HTTPStatusError as exc:
        raise DocumentDownloadError(f"HTTP {exc.response.status_code}") from None
    except httpx.HTTPError as exc:
        raise DocumentDownloadError(
            f"HTTP transport failure ({type(exc).__name__})"
        ) from None
    except OSError:
        raise DocumentDownloadError("Local document storage failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                raise DocumentDownloadError("Partial document cleanup failed") from None
