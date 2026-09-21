import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import httpx2
from openai import DefaultHttpxClient
from pydantic import SecretStr
from rag_fixtures import CHUNKING, EMBEDDING, RagDatabaseMixin, vector
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_openai_client import response_body

from app.ai.client import ProviderError
from app.ai.embeddings import OpenAIEmbeddingClient
from app.ai.openai_client import OpenAIStructuredClient
from app.ask import main as ask_main
from app.index_document import main as index_main
from app.models import DocumentChunk, TenderQuestion
from app.rag.schemas import TenderAnswerOutput
from app.services.indexing import index_document


class RagSDKTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        blocker = patch(
            "socket.socket.connect", side_effect=AssertionError("No live API")
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def transport(self, body, status=200):
        def respond(request):
            self.requests.append(request)
            return httpx2.Response(status, json=body)

        return DefaultHttpxClient(
            transport=httpx2.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        )

    def embedding_client(self, records, status=200):
        client = OpenAIEmbeddingClient(
            SecretStr("test-only"),
            http_client=self.transport(
                {
                    "object": "list",
                    "data": records,
                    "model": "test-model",
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
                status,
            ),
        )
        self.addCleanup(client.close)
        return client

    def test_sdk_batch_dimensions_float_encoding_and_response_order(self):
        client = self.embedding_client(
            [
                {"object": "embedding", "index": 1, "embedding": vector(0, 1)},
                {"object": "embedding", "index": 0, "embedding": vector()},
            ]
        )
        vectors = client.embed(["A", "B"], model="test-model", dimensions=1536)
        self.assertEqual(vectors, [vector(), vector(0, 1)])
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["input"], ["A", "B"])
        self.assertEqual(body["dimensions"], 1536)
        self.assertEqual(body["encoding_format"], "float")
        self.assertEqual(self.requests[0].url.path, "/v1/embeddings")

    def test_sdk_bad_count_index_dimensions_and_http_failure(self):
        for records, status in (
            ([], 200),
            ([{"object": "embedding", "index": 1, "embedding": vector()}], 200),
            ([{"object": "embedding", "index": 0, "embedding": [1, 0, 0]}], 200),
            ([], 401),
        ):
            with self.assertRaises(ProviderError) as error:
                self.embedding_client(records, status).embed(
                    ["A"], model="test", dimensions=1536
                )
            self.assertNotIn("test-only", str(error.exception))

    def test_answer_sdk_uses_dedicated_strict_schema(self):
        response = json.dumps(
            {
                "answer": "1 June",
                "citations": [{"chunk_id": 1, "quote": "Deadline 1 June"}],
                "insufficient_evidence": False,
            }
        )
        client = OpenAIStructuredClient(
            SecretStr("test-only"),
            http_client=self.transport(response_body(response)),
            output_schema=TenderAnswerOutput,
        )
        self.addCleanup(client.close)
        actual = client.generate(
            model="test-model", instructions="untrusted data", text="context"
        )
        self.assertEqual(json.loads(actual), json.loads(response))
        body = json.loads(self.requests[0].content)
        self.assertFalse(body["store"])
        self.assertEqual(body["truncation"], "disabled")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(
            body["text"]["format"]["schema"]["title"], "TenderAnswerOutput"
        )
        self.assertNotIn("tools", body)


class RagCLITests(RagDatabaseMixin, unittest.TestCase):
    def count(self, model):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(model))

    def test_prepare_only_without_ai_credentials_has_no_side_effects(self):
        output = StringIO()
        with (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-only"}, clear=True),
            patch(
                "app.index_document.create_database_engine", return_value=self.engine
            ),
            patch.object(self.engine, "dispose"),
            patch("app.index_document.OpenAIEmbeddingClient") as client,
            redirect_stdout(output),
        ):
            self.assertEqual(
                index_main(
                    ["--document-version-id", str(self.version_id), "--prepare-only"]
                ),
                0,
            )
        client.assert_not_called()
        self.assertIn("chunk_count=1", output.getvalue())
        self.assertIn("persisted=false", output.getvalue())
        self.assertNotIn("June", output.getvalue())
        self.assertEqual(self.count(DocumentChunk), 0)

    def test_index_cli_and_ask_modes_with_test_clients(self):
        env = {
            "POSTGRES_PASSWORD": "test-only",
            "OPENAI_API_KEY": "test-only",
            "AI_EMBEDDING_MODEL": EMBEDDING.model,
            "AI_MODEL": "synthetic-answer",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(self.engine, "dispose"),
            patch(
                "app.index_document.create_database_engine", return_value=self.engine
            ),
            patch("app.ask.create_database_engine", return_value=self.engine),
            patch(
                "app.index_document.OpenAIEmbeddingClient", return_value=self.embedder
            ),
            patch("app.ask.OpenAIEmbeddingClient", return_value=self.embedder),
            patch(
                "app.ask.OpenAIStructuredClient", return_value=self.answerer
            ) as answer_client,
        ):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    index_main(["--document-version-id", str(self.version_id)]), 0
                )
            self.assertIn("embeddings_created=1", output.getvalue())
            args = [
                "--document-version-id",
                str(self.version_id),
                "--question",
                "Deadline?",
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(ask_main([*args, "--retrieve-only"]), 0)
            self.assertIn("rank=1 chunk_id=", output.getvalue())
            answer_client.assert_not_called()
            self.assertEqual(self.count(TenderQuestion), 0)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(ask_main(args), 0)
            self.assertIn("status=completed", output.getvalue())
            self.assertIn("chunk_index=0", output.getvalue())
            self.assertNotIn("test-only", output.getvalue())

    def test_missing_credentials_fail_before_network(self):
        with (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test"}, clear=True),
            patch("app.ask.OpenAIEmbeddingClient") as client,
            self.assertLogs("app.ask", level="ERROR"),
        ):
            self.assertEqual(
                ask_main(
                    [
                        "--document-version-id",
                        "1",
                        "--question",
                        "Deadline?",
                        "--retrieve-only",
                    ]
                ),
                1,
            )
        client.assert_not_called()

    def test_insufficient_cli_and_failed_cli_status(self):
        index_document(
            self.engine,
            self.version_id,
            self.embedder,
            embedding=EMBEDDING,
            chunking=CHUNKING,
        )
        env = {
            "POSTGRES_PASSWORD": "test-only",
            "OPENAI_API_KEY": "test-only",
            "AI_EMBEDDING_MODEL": EMBEDDING.model,
            "AI_MODEL": "synthetic-answer",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(self.engine, "dispose"),
            patch("app.ask.create_database_engine", return_value=self.engine),
            patch("app.ask.OpenAIEmbeddingClient", return_value=self.embedder),
            patch("app.ask.OpenAIStructuredClient", return_value=self.answerer),
        ):
            for response, question, code, expected in (
                (
                    json.dumps(
                        {"answer": None, "citations": [], "insufficient_evidence": True}
                    ),
                    "Unknown?",
                    0,
                    "not established by the indexed tender text",
                ),
                ("malformed secret", "Other?", 1, "status=failed"),
            ):
                self.answerer.response = response
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        ask_main(
                            [
                                "--document-version-id",
                                str(self.version_id),
                                "--question",
                                question,
                            ]
                        ),
                        code,
                    )
                self.assertIn(expected, output.getvalue())
                self.assertNotIn("secret", output.getvalue())
