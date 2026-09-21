import math
import struct
from typing import Protocol

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    DefaultHttpxClient,
    OpenAI,
)
from pydantic import SecretStr

from app.ai.client import ProviderError, ProviderFailure


class EmbeddingClient(Protocol):
    provider: str

    def embed(
        self, texts: list[str], *, model: str, dimensions: int
    ) -> list[list[float]]: ...


def validate_vectors(vectors: object, count: int, dimensions: int) -> list[list[float]]:
    try:
        if not isinstance(vectors, list) or len(vectors) != count:
            raise ValueError
        validated = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ValueError
            if any(type(value) not in (int, float) for value in vector):
                raise ValueError
            values = [
                struct.unpack("f", struct.pack("f", value))[0] for value in vector
            ]
            if not all(math.isfinite(value) for value in values) or not any(values):
                raise ValueError
            validated.append(values)
        return validated
    except (ValueError, OverflowError, struct.error):
        raise ProviderError(ProviderFailure.INVALID_OUTPUT) from None


def embed_batch(
    client: EmbeddingClient, texts: list[str], *, model: str, dimensions: int
) -> list[list[float]]:
    try:
        vectors = client.embed(texts, model=model, dimensions=dimensions)
        return validate_vectors(vectors, len(texts), dimensions)
    except ProviderError:
        raise
    except Exception:
        raise ProviderError(ProviderFailure.API) from None


class OpenAIEmbeddingClient:
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

    def embed(
        self, texts: list[str], *, model: str, dimensions: int
    ) -> list[list[float]]:
        try:
            response = self._client.embeddings.create(
                input=texts, model=model, dimensions=dimensions, encoding_format="float"
            )
            records = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in records] != list(range(len(texts))):
                raise ValueError
            return validate_vectors(
                [item.embedding for item in records], len(texts), dimensions
            )
        except APITimeoutError:
            raise ProviderError(ProviderFailure.TIMEOUT) from None
        except APIConnectionError:
            raise ProviderError(ProviderFailure.CONNECTION) from None
        except APIError:
            raise ProviderError(ProviderFailure.API) from None
        except (ValueError, TypeError, AttributeError):
            raise ProviderError(ProviderFailure.INVALID_OUTPUT) from None

    def close(self) -> None:
        self._client.close()
