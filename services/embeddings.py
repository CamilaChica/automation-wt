"""Retrying OpenAI and Hugging Face embedding adapters."""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import requests


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    provider: str
    model: str
    dimensions: int


class EmbeddingError(RuntimeError):
    pass


class OpenAIEmbeddingProvider:
    name = "openai"
    model = "text-embedding-3-small"
    dimensions = 1536

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingError("OPENAI_API_KEY is required for OpenAI embeddings.")
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": list(texts), "dimensions": self.dimensions},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        rows = sorted(payload["data"], key=lambda row: row["index"])
        return [[float(value) for value in row["embedding"]] for row in rows]


class HuggingFaceEmbeddingProvider:
    name = "huggingface"
    model = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions = 384

    def __init__(self, api_token: str | None = None, endpoint: str | None = None, timeout: float = 30.0):
        self.api_token = api_token or os.getenv("HUGGINGFACE_API_TOKEN")
        self.endpoint = endpoint or f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.model}"
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_token:
            raise EmbeddingError("HUGGINGFACE_API_TOKEN is required for Hugging Face embeddings.")
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_token}"},
            json={"inputs": list(texts), "options": {"wait_for_model": True}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._pool_response(response.json(), len(texts))

    @classmethod
    def _pool_response(cls, payload: object, expected_count: int) -> list[list[float]]:
        if not isinstance(payload, list) or not payload:
            raise EmbeddingError("Hugging Face returned an invalid embedding payload.")
        if isinstance(payload[0], (int, float)):
            rows = [payload]
        elif isinstance(payload[0], list) and payload[0] and isinstance(payload[0][0], (int, float)):
            if expected_count == 1 and len(payload) != 1:
                rows = [cls._mean_pool(payload)]
            else:
                rows = payload
        else:
            rows = [cls._mean_pool(tokens) for tokens in payload]
        return [[float(value) for value in row] for row in rows]

    @staticmethod
    def _mean_pool(token_vectors: object) -> list[float]:
        if not isinstance(token_vectors, list) or not token_vectors:
            raise EmbeddingError("Hugging Face returned an empty token embedding.")
        width = len(token_vectors[0])
        if not width or any(not isinstance(vector, list) or len(vector) != width for vector in token_vectors):
            raise EmbeddingError("Hugging Face returned inconsistent token dimensions.")
        return [sum(float(vector[index]) for vector in token_vectors) / len(token_vectors) for index in range(width)]


class EmbeddingService:
    def __init__(
        self,
        providers: Sequence[EmbeddingProvider] | None = None,
        *,
        retries: int = 2,
        retry_delay_seconds: float = 0.25,
    ):
        if retries < 1:
            raise ValueError("retries must be at least one.")
        self.providers = list(providers or [OpenAIEmbeddingProvider(), HuggingFaceEmbeddingProvider()])
        self.retries = retries
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def embed(self, texts: Sequence[str], *, preferred_provider: str | None = None) -> EmbeddingBatch:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding input must contain non-empty text values.")
        providers = self.providers
        if preferred_provider:
            providers = sorted(providers, key=lambda provider: provider.name != preferred_provider)
        errors: list[str] = []
        for provider in providers:
            for attempt in range(self.retries):
                try:
                    vectors = provider.embed(texts)
                    self._validate_vectors(vectors, expected_count=len(texts), dimensions=provider.dimensions)
                    return EmbeddingBatch(vectors, provider.name, provider.model, provider.dimensions)
                except Exception as exc:
                    errors.append(f"{provider.name} attempt {attempt + 1}: {type(exc).__name__}: {exc}")
                    if attempt + 1 < self.retries and self.retry_delay_seconds:
                        time.sleep(self.retry_delay_seconds * (2 ** attempt))
        raise EmbeddingError("All embedding providers failed: " + "; ".join(errors))

    @staticmethod
    def _validate_vectors(vectors: list[list[float]], *, expected_count: int, dimensions: int) -> None:
        if len(vectors) != expected_count:
            raise ValueError(f"Expected {expected_count} embeddings, got {len(vectors)}.")
        for vector in vectors:
            if len(vector) != dimensions or any(not math.isfinite(value) for value in vector):
                raise ValueError(f"Embedding must contain {dimensions} finite values.")