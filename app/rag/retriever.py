"""Hybrid vector and BM25 retrieval over the local SQLite index."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from app.domain.models import DocumentChunk, RetrievalEvidence
from app.embeddings.providers import embedding_tokens
from app.embeddings.gateway import EmbeddingProvider
from app.rag.reranker import normalize_scores, rerank
from app.storage.metadata import SQLiteIndex


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


class BM25Index:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks
        self.tokens = [embedding_tokens(chunk.content) for chunk in chunks]
        self.document_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))
        self.average_length = sum(map(len, self.tokens)) / len(self.tokens) if self.tokens else 0.0
        self.k1 = 1.5
        self.b = 0.75

    def scores(self, query: str) -> list[float]:
        query_tokens = embedding_tokens(query)
        if not query_tokens or not self.chunks:
            return [0.0] * len(self.chunks)
        query_terms = Counter(query_tokens)
        document_count = len(self.chunks)
        scores: list[float] = []
        for tokens in self.tokens:
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term, query_count in query_terms.items():
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency.get(term, 0)
                idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / self.average_length
                ) if self.average_length else 1.0
                score += idf * (frequency * (self.k1 + 1.0) / denominator) * query_count
            scores.append(score)
        return scores


class HybridRetriever:
    def __init__(self, repository: SQLiteIndex, embedding_provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def search(self, query: str, project_id: str = "default", top_k: int = 5) -> list[RetrievalEvidence]:
        chunks = self.repository.list_chunks(project_id)
        if not chunks:
            return []
        query_vector = self.embedding_provider.embed(query)
        vector_pairs = sorted(
            ((chunk, max(-1.0, min(1.0, _cosine(query_vector, chunk.vector)))) for chunk in chunks),
            key=lambda pair: (-pair[1], pair[0].chunk_id),
        )[:10]
        bm25 = BM25Index(chunks)
        bm25_values = bm25.scores(query)
        bm25_pairs = sorted(
            zip(chunks, bm25_values, strict=True),
            key=lambda pair: (-pair[1], pair[0].chunk_id),
        )[:10]
        vector_values = normalize_scores([score for _, score in vector_pairs])
        bm25_top_values = normalize_scores([score for _, score in bm25_pairs])
        merged: dict[str, RetrievalEvidence] = {}
        for (chunk, raw_vector), normalized_vector in zip(vector_pairs, vector_values, strict=True):
            merged[chunk.chunk_id] = _evidence(chunk, normalized_vector, 0.0)
        for (chunk, raw_bm25), normalized_bm25 in zip(bm25_pairs, bm25_top_values, strict=True):
            existing = merged.get(chunk.chunk_id)
            vector_score = existing.vector_score if existing else 0.0
            merged[chunk.chunk_id] = _evidence(chunk, vector_score, normalized_bm25)
        return rerank(list(merged.values()))[:top_k]


def _evidence(chunk: DocumentChunk, vector_score: float, bm25_score: float) -> RetrievalEvidence:
    return RetrievalEvidence(
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        source_file=chunk.source_file,
        relative_path=chunk.relative_path,
        document_type=chunk.document_type,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        vector_score=round(vector_score, 6),
        bm25_score=round(bm25_score, 6),
        index_fingerprint=chunk.index_fingerprint,
        external_allowed=chunk.external_allowed,
        chunk_strategy=chunk.chunk_strategy,
    )


_QUESTION_BIGRAMS = frozenset({"什么", "如何", "哪个", "哪些", "多少", "怎么", "请问", "应该"})


def _gate_terms(text: str) -> tuple[set[str], set[str]]:
    ascii_terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", text)}
    chinese_terms: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for phrase in _QUESTION_BIGRAMS:
            run = run.replace(phrase, "")
        chinese_terms.update(
            run[index : index + 2]
            for index in range(len(run) - 1)
        )
    return ascii_terms, chinese_terms


def has_lexical_overlap(query: str, content: str) -> bool:
    query_ascii, query_chinese = _gate_terms(query)
    content_ascii, content_chinese = _gate_terms(content)
    ascii_overlap = query_ascii.intersection(content_ascii)
    if query_ascii and not ascii_overlap:
        return False
    if len(ascii_overlap) >= 2:
        return True
    if query_chinese and not query_chinese.intersection(content_chinese):
        return False
    return bool(ascii_overlap or query_chinese.intersection(content_chinese))
