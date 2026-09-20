"""Explainable score normalization and hybrid reranking."""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import RetrievalEvidence


def normalize_scores(scores: Iterable[float]) -> list[float]:
    values = list(scores)
    if not values:
        return []
    low, high = min(values), max(values)
    if high == low:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def combine_scores(vector_score: float, bm25_score: float, vector_weight: float = 0.7) -> float:
    if not 0.0 <= vector_weight <= 1.0:
        raise ValueError("vector_weight must be between 0 and 1")
    return round(vector_weight * vector_score + (1.0 - vector_weight) * bm25_score, 6)


def rerank(evidence: list[RetrievalEvidence], vector_weight: float = 0.7) -> list[RetrievalEvidence]:
    ranked = [
        item.model_copy(update={"score": combine_scores(item.vector_score, item.bm25_score, vector_weight)})
        for item in evidence
    ]
    return sorted(ranked, key=lambda item: (-item.score, item.chunk_id))

