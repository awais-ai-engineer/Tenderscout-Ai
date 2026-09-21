import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
from openai import DefaultHttpxClient
from pydantic import SecretStr

from app.ai.client import ProviderError, ProviderFailure
from app.ai.openai_client import OpenAIStructuredClient
from app.ai.prompt import TENDER_ANALYSIS_PROMPT

RESPONSE = (Path(__file__).parent / "fixtures" / "analysis_response.json").read_text()


def response_body(text=RESPONSE, status="completed", refusal=False):
    content = (
        {"type": "refusal", "refusal": "Refused"}
        if refusal
        else {"type": "output_text", "text": text, "annotations": []}
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": status,
        "model": "test-model",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [content],
            }
        ],
    }


class OpenAIClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = []
        blocker = patch(
            "socket.create_connection",
            side_effect=AssertionError("External LLM call forbidden"),
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def client(self, response=None, error=None):
        def respond(request):
            self.requests.append(request)
            if error:
                raise error
            return response or httpx2.Response(200, json=response_body())

        transport = httpx2.MockTransport(respond)
        http_client = DefaultHttpxClient(
            transport=transport, follow_redirects=False, trust_env=False
        )
        client = OpenAIStructuredClient(
            SecretStr("test-only-key"), http_client=http_client
        )
        self.addCleanup(client.close)
        return client

    def generate(self, client):
        return client.generate(
            model="test-model",
            instructions=TENDER_ANALYSIS_PROMPT.instructions,
            text="Document source text",
        )

    def test_real_sdk_sends_strict_schema_and_parses_mocked_response(self) -> None:
        output = self.generate(self.client())
        self.assertEqual(json.loads(output), json.loads(RESPONSE))
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(
            body["input"][1], {"role": "user", "content": "Document source text"}
        )
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        schema = body["text"]["format"]["schema"]
        for node in [schema, *schema["$defs"].values()]:
            self.assertFalse(node["additionalProperties"])
            self.assertEqual(set(node["required"]), set(node["properties"]))
        self.assertFalse(body["store"])
        self.assertEqual(body["truncation"], "disabled")
        self.assertEqual(body["max_output_tokens"], 8000)
        self.assertNotIn("tools", body)
        self.assertEqual(request.extensions["timeout"]["read"], 60)

    def test_provider_http_errors_are_sanitized_and_not_retried(self) -> None:
        for status in (401, 429, 500):
            before = len(self.requests)
            response = httpx2.Response(
                status,
                json={
                    "error": {
                        "message": "test-only-key sensitive transport",
                        "type": "error",
                    }
                },
            )
            with self.subTest(status=status), self.assertRaises(ProviderError) as error:
                self.generate(self.client(response))
            self.assertEqual(error.exception.reason, ProviderFailure.API)
            self.assertNotIn("test-only-key", str(error.exception))
            self.assertEqual(len(self.requests) - before, 1)

    def test_timeout_is_sanitized_without_retry(self) -> None:
        with self.assertRaises(ProviderError) as error:
            self.generate(self.client(error=httpx2.ReadTimeout("test-only-key")))
        self.assertEqual(error.exception.reason, ProviderFailure.TIMEOUT)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("test-only-key", str(error.exception))

    def test_refusal_and_incomplete_response_are_failures(self) -> None:
        for body, reason in (
            (response_body(refusal=True), ProviderFailure.REFUSAL),
            (response_body(status="incomplete"), ProviderFailure.INCOMPLETE),
        ):
            with self.subTest(reason=reason), self.assertRaises(ProviderError) as error:
                self.generate(self.client(httpx2.Response(200, json=body)))
            self.assertEqual(error.exception.reason, reason)

    def test_invalid_output_is_rejected_by_real_sdk_parser(self) -> None:
        for output in ('{"unrecognized":true}', "not json"):
            with self.subTest(output=output), self.assertRaises(ProviderError) as error:
                self.generate(
                    self.client(httpx2.Response(200, json=response_body(output)))
                )
            self.assertEqual(error.exception.reason, ProviderFailure.INVALID_OUTPUT)

    def test_endpoint_cannot_be_changed_by_environment(self) -> None:
        with patch.dict(
            "os.environ", {"OPENAI_BASE_URL": "https://untrusted.example/v1"}
        ):
            self.generate(self.client())
        self.assertEqual(self.requests[0].url.host, "api.openai.com")

    def test_commentary_is_not_mixed_into_final_structured_output(self) -> None:
        body = response_body()
        body["output"].insert(
            0,
            {
                "type": "message",
                "id": "msg_commentary",
                "role": "assistant",
                "status": "completed",
                "phase": "commentary",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Reading source.",
                        "annotations": [],
                    }
                ],
            },
        )
        output = self.generate(self.client(httpx2.Response(200, json=body)))
        self.assertEqual(json.loads(output), json.loads(RESPONSE))

    def test_redirect_is_not_followed(self) -> None:
        with self.assertRaises(ProviderError):
            self.generate(
                self.client(
                    httpx2.Response(
                        307, headers={"Location": "https://untrusted.example"}
                    )
                )
            )
        self.assertEqual(len(self.requests), 1)
