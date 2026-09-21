from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    DefaultHttpxClient,
    OpenAI,
)
from pydantic import SecretStr, ValidationError

from app.ai.client import ProviderError, ProviderFailure
from app.ai.schemas import TenderAnalysisOutput


class OpenAIStructuredClient:
    provider = "openai"

    def __init__(
        self, api_key: SecretStr, *, http_client: DefaultHttpxClient | None = None
    ):
        self._client = OpenAI(
            api_key=api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=60.0,
            max_retries=0,
            http_client=http_client
            or DefaultHttpxClient(trust_env=False, follow_redirects=False),
        )

    def generate(self, *, model: str, instructions: str, text: str) -> str:
        try:
            response = self._client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text},
                ],
                text_format=TenderAnalysisOutput,
                max_output_tokens=8000,
                truncation="disabled",
                store=False,
            )
        except APITimeoutError:
            raise ProviderError(ProviderFailure.TIMEOUT) from None
        except APIConnectionError:
            raise ProviderError(ProviderFailure.CONNECTION) from None
        except APIError:
            raise ProviderError(ProviderFailure.API) from None
        except (ValidationError, ValueError):
            raise ProviderError(ProviderFailure.INVALID_OUTPUT) from None
        if response.status != "completed":
            raise ProviderError(ProviderFailure.INCOMPLETE)
        if response.output_parsed is None or any(
            item.type == "message"
            and any(content.type == "refusal" for content in item.content)
            for item in response.output
        ):
            raise ProviderError(ProviderFailure.REFUSAL)
        return response.output_parsed.model_dump_json()

    def close(self) -> None:
        self._client.close()
