"""Embedding provider boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    dimension: int
    provider_name: str
    model_name: str
    is_remote: bool

    @property
    def fingerprint(self) -> str:
        ...

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class EmbeddingGateway:
    """Small facade that keeps provider selection out of RAG business logic."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    @property
    def dimension(self) -> int:
        return self.provider.dimension

    def embed(self, text: str) -> list[float]:
        return self.provider.embed(text)

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return self.provider.embed_many(texts)
