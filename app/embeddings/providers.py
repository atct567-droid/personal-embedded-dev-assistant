"""Deterministic offline and optional OpenAI-compatible embedding providers."""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from urllib.parse import urlsplit
from collections.abc import Sequence
from dataclasses import dataclass
import re

from app.domain.errors import InvalidInputError


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]")


def embedding_tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


@dataclass(slots=True)
class MockEmbeddingProvider:
    """Stable hash-based vectors for repeatable tests, not semantic embeddings."""

    dimension: int = 96
    provider_name: str = "mock"
    model_name: str = "deterministic-hash-v1"
    is_remote: bool = False

    @property
    def fingerprint(self) -> str:
        return f"{self.provider_name}:{self.model_name}:{self.dimension}"

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise InvalidInputError("Embedding 输入必须是文本")
        vector = [0.0] * self.dimension
        for token in embedding_tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            magnitude = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * magnitude
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [round(value / norm, 8) for value in vector]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


@dataclass(slots=True)
class OpenAICompatibleEmbeddingProvider:
    """Optional HTTP adapter; callers must opt in and provide a key explicitly."""

    base_url: str
    api_key: str
    model: str
    dimension: int = 0
    timeout_seconds: float = 20.0
    provider_name: str = "openai-compatible"
    is_remote: bool = True

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def fingerprint(self) -> str:
        endpoint = urlsplit(self.base_url).netloc.lower()
        endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]
        return f"{self.provider_name}:{endpoint_hash}:{self.model}:{self.dimension}"

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            raise InvalidInputError("真实 Embedding provider 未配置 API Key")
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        vectors = [item["embedding"] for item in sorted(body["data"], key=lambda item: item["index"])]
        if vectors and self.dimension == 0:
            self.dimension = len(vectors[0])
        return vectors
