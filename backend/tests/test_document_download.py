import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from app.services.document_download import (
    DocumentDownloadError,
    allowed_url,
    download_pdf,
)

URL = "https://www.contractsfinder.service.gov.uk/Notice/Attachment/test"
PDF = (Path(__file__).parent / "fixtures" / "tiny_text.pdf").read_bytes()


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], fail: bool = False):
        self.chunks = chunks
        self.fail = fail
        self.visited = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.visited += 1
            yield chunk
        if self.fail:
            raise httpx.ReadTimeout("sensitive transport detail")

    def close(self):
        self.closed = True


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Path(directory.name)

    def download(self, response: httpx.Response, max_bytes: int = 26214400):
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: response)
        ) as client:
            return download_pdf(client, URL, self.storage, max_bytes)

    def assert_clean(self) -> None:
        self.assertEqual([p for p in self.storage.rglob("*") if p.is_file()], [])

    def test_real_pdf_stream_hash_path_user_agent_and_identical_storage(self) -> None:
        requests = []
        streams = []

        def respond(request):
            requests.append(request)
            stream = Chunks([PDF[:3], PDF[3:100], PDF[100:]])
            streams.append(stream)
            return httpx.Response(
                200,
                stream=stream,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'attachment; filename="../../escape.pdf"',
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), follow_redirects=True
        ) as client:
            first = download_pdf(client, URL, self.storage, len(PDF))
            second = download_pdf(client, URL, self.storage, len(PDF))
        digest = hashlib.sha256(PDF).hexdigest()
        self.assertEqual(first.content_hash, digest)
        self.assertEqual(len(digest), 64)
        self.assertEqual(first.byte_size, len(PDF))
        self.assertEqual(first.storage_path, f"{digest[:2]}/{digest}.pdf")
        self.assertEqual(second.storage_path, first.storage_path)
        self.assertEqual((self.storage / first.storage_path).read_bytes(), PDF)
        self.assertEqual(len(list(self.storage.rglob("*.pdf"))), 1)
        self.assertEqual(list(self.storage.glob("*.part")), [])
        for request, stream in zip(requests, streams, strict=True):
            self.assertIn("TenderScoutAI", request.headers["User-Agent"])
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            self.assertEqual(request.extensions["timeout"]["read"], 30)
            self.assertEqual(stream.visited, 3)
            self.assertTrue(stream.closed)

    def test_octet_stream_with_pdf_magic_is_accepted(self) -> None:
        result = self.download(
            httpx.Response(
                200, content=PDF, headers={"Content-Type": "application/octet-stream"}
            )
        )
        self.assertEqual(result.byte_size, len(PDF))

    def test_disallowed_urls_are_rejected_before_http(self) -> None:
        requests = []
        urls = [
            URL.replace("https:", "http:"),
            URL.replace("www.contractsfinder.service.gov.uk", "evil.example"),
            URL.replace(".gov.uk", ".gov.uk.evil.example"),
            URL.replace("https://", "https://user:password@"),
            URL.replace(".gov.uk/", ".gov.uk:444/"),
            "https://127.0.0.1/file.pdf",
            "https://www.contractsfinder.service.gov.uk:invalid/file.pdf",
        ]
        with httpx.Client(
            transport=httpx.MockTransport(lambda r: requests.append(r))
        ) as client:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(DocumentDownloadError):
                    download_pdf(client, url, self.storage, 1024)
        self.assertEqual(requests, [])
        self.assertTrue(allowed_url(URL.replace(".gov.uk/", ".gov.uk:443/")))
        self.assert_clean()

    def test_redirects_and_http_failures_do_not_retry(self) -> None:
        for status in (301, 302, 307, 308, 403, 404, 500):
            requests = []

            def respond(request):
                requests.append(request)
                return httpx.Response(
                    status, headers={"Location": "https://evil.example/private"}
                )

            with (
                self.subTest(status=status),
                httpx.Client(
                    transport=httpx.MockTransport(respond), follow_redirects=True
                ) as client,
                self.assertRaisesRegex(DocumentDownloadError, f"HTTP {status}"),
            ):
                download_pdf(client, URL, self.storage, 1024)
            self.assertEqual(len(requests), 1)
            self.assert_clean()

    def test_content_length_checked_before_consuming_stream(self) -> None:
        for length in ("1001", "-1", "invalid"):
            stream = Chunks([PDF])
            with self.subTest(length=length), self.assertRaises(DocumentDownloadError):
                self.download(
                    httpx.Response(
                        200,
                        stream=stream,
                        headers={
                            "Content-Type": "application/pdf",
                            "Content-Length": length,
                        },
                    ),
                    1000,
                )
            self.assertEqual(stream.visited, 0)
            self.assertTrue(stream.closed)
            self.assert_clean()

    def test_actual_stream_limit_cleans_partial_file(self) -> None:
        stream = Chunks([b"%PDF-" + b"x" * 65531, b"x" * 65536, b"not reached"])
        with self.assertRaisesRegex(DocumentDownloadError, "Stream exceeds"):
            self.download(
                httpx.Response(
                    200,
                    stream=stream,
                    headers={"Content-Type": "application/pdf", "Content-Length": "1"},
                ),
                70000,
            )
        self.assertEqual(stream.visited, 2)
        self.assertTrue(stream.closed)
        self.assert_clean()

    def test_non_pdf_and_html_are_rejected(self) -> None:
        for content, media in (
            (b"not a pdf", "application/pdf"),
            (b"<html>Error</html>", "application/pdf"),
            (PDF, "text/html"),
            (b"", "application/octet-stream"),
        ):
            with (
                self.subTest(media=media, content=content[:10]),
                self.assertRaises(DocumentDownloadError),
            ):
                self.download(
                    httpx.Response(
                        200, content=content, headers={"Content-Type": media}
                    )
                )
            self.assert_clean()

    def test_timeout_after_partial_write_is_sanitized_and_cleaned(self) -> None:
        stream = Chunks([b"%PDF-" + b"x" * 65531], fail=True)
        with self.assertRaises(DocumentDownloadError) as error:
            self.download(
                httpx.Response(
                    200, stream=stream, headers={"Content-Type": "application/pdf"}
                )
            )
        self.assertIn("ReadTimeout", str(error.exception))
        self.assertNotIn("sensitive", str(error.exception))
        self.assertTrue(stream.closed)
        self.assert_clean()

    def test_encoded_body_is_rejected_before_decompression(self) -> None:
        stream = Chunks([b"not gzip"])
        with self.assertRaisesRegex(DocumentDownloadError, "Encoded"):
            self.download(
                httpx.Response(
                    200,
                    stream=stream,
                    headers={
                        "Content-Type": "application/pdf",
                        "Content-Encoding": "gzip",
                    },
                )
            )
        self.assertEqual(stream.visited, 0)
        self.assert_clean()
