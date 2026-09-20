from pathlib import Path

import pytest

from app.config import Settings
from app.embeddings.providers import MockEmbeddingProvider
from app.llm.gateway import LLMGateway
from app.llm.providers import MockLLMProvider
from app.domain.errors import PolicyDeniedError
from app.domain.models import RetrievalEvidence
from app.rag.answer import REFUSAL_TEXT, RAGAnswerService
from app.rag.indexer import DocumentIndexer
from app.rag.reranker import combine_scores
from app.rag.retriever import HybridRetriever, has_lexical_overlap
from app.storage.metadata import SQLiteIndex


def _service(tmp_path: Path) -> RAGAnswerService:
    settings = Settings.from_root(tmp_path)
    repository = SQLiteIndex(settings)
    embeddings = MockEmbeddingProvider()
    indexer = DocumentIndexer(repository, embeddings)
    source = tmp_path / "uart.md"
    source.write_text(
        "# UART 初始化\nPA9 作为 TX，PA10 作为 RX。\n\n"
        "# 故障排查\n先检查波特率，再检查地线。",
        encoding="utf-8",
    )
    indexer.ingest_file(source, relative_path="uart.md")
    return RAGAnswerService(HybridRetriever(repository, embeddings), LLMGateway(MockLLMProvider()))


def test_baseline_rerank_formula_is_explainable() -> None:
    assert combine_scores(1.0, 0.0) == 0.7
    assert combine_scores(0.0, 1.0) == 0.3


def test_rag_returns_evidence_and_citations(tmp_path: Path) -> None:
    response = _service(tmp_path).answer("PA9 是什么？", trace_id="trace-test")
    assert response.answer != REFUSAL_TEXT
    assert response.citations
    assert response.citations[0].source_file == "uart.md"
    assert response.trace_id == "trace-test"


def test_rag_refuses_unknown_question(tmp_path: Path) -> None:
    response = _service(tmp_path).answer("SPI DMA 的时钟树如何配置？")
    assert response.answer == REFUSAL_TEXT
    assert response.citations == []


def test_gate_ignores_generic_single_character_matches() -> None:
    content = "UART 使用 GPIO 初始化。"
    assert not has_lexical_overlap("机械限位开关 GPIO", content)
    assert has_lexical_overlap("PA9 是什么？", "PA9 作为 TX。")


def test_remote_llm_requires_request_and_document_authorization(tmp_path: Path) -> None:
    class RemoteProvider:
        name = "remote-test"
        model_name = "fake"
        is_remote = True

        def generate(self, prompt, evidence):
            del prompt
            return evidence[0].content if evidence else "现有资料不足以确定。"

    service = _service(tmp_path)
    service.llm = LLMGateway(RemoteProvider())
    evidence = [
        RetrievalEvidence(
            chunk_id="chunk-1",
            content="PA9 作为 TX。",
            source_file="uart.md",
            relative_path="uart.md",
            document_type="md",
            external_allowed=False,
        )
    ]
    with pytest.raises(PolicyDeniedError):
        service.answer_from_evidence("PA9 是什么？", evidence)
    with pytest.raises(PolicyDeniedError):
        service.answer_from_evidence(
            "PA9 是什么？", evidence, allow_external_processing=True
        )
    evidence[0].external_allowed = True
    assert "PA9" in service.answer_from_evidence(
        "PA9 是什么？", evidence, allow_external_processing=True
    )
