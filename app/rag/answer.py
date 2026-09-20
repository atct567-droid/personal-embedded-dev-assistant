"""Evidence-gated answer generation with source citations."""

from __future__ import annotations

from app.domain.models import Citation, CitationResponse, RetrievalEvidence
from app.domain.errors import PolicyDeniedError
from app.llm.gateway import LLMGateway
from app.rag.retriever import HybridRetriever, has_lexical_overlap


REFUSAL_TEXT = "现有资料不足以确定。"


class RAGAnswerService:
    def __init__(self, retriever: HybridRetriever, llm: LLMGateway) -> None:
        self.retriever = retriever
        self.llm = llm

    def answer(
        self,
        question: str,
        project_id: str = "default",
        top_k: int = 5,
        trace_id: str = "trace-local",
        session_id: str | None = None,
        conversation_context: str = "",
        retrieval_context: str = "",
        allow_external_processing: bool = False,
    ) -> CitationResponse:
        retrieval_query = f"{retrieval_context}\n{question}".strip()
        retrieved = self.retriever.search(
            retrieval_query, project_id=project_id, top_k=max(top_k, 6)
        )
        supported = [
            item
            for item in retrieved
            if item.bm25_score > 0.0
            and has_lexical_overlap(
                retrieval_query, f"{item.section_title or ''}\n{item.content}"
            )
        ][:top_k]
        if not supported:
            return CitationResponse(
                answer=REFUSAL_TEXT,
                confidence="low",
                citations=[],
                trace_id=trace_id,
                session_id=session_id,
            )
        answer = self.answer_from_evidence(
            question,
            supported,
            conversation_context=conversation_context,
            allow_external_processing=allow_external_processing,
        )
        confidence = "high" if supported[0].score >= 0.65 else "medium"
        citations = [
            Citation(
                source_file=item.source_file,
                section=item.section_title,
                page=item.page_number,
                chunk_id=item.chunk_id,
                score=max(0.0, min(1.0, item.score)),
            )
            for item in supported
        ]
        return CitationResponse(
            answer=answer,
            confidence=confidence,
            citations=citations,
            trace_id=trace_id,
            session_id=session_id,
        )

    def answer_from_evidence(
        self,
        question: str,
        evidence: list[RetrievalEvidence],
        *,
        conversation_context: str = "",
        allow_external_processing: bool = False,
    ) -> str:
        if self.llm.is_remote:
            if not allow_external_processing:
                raise PolicyDeniedError("远程 LLM 需要本次查询显式授权")
            if any(not item.external_allowed for item in evidence):
                raise PolicyDeniedError("检索证据包含禁止外发的文档")
        return self.llm.answer(question, evidence, conversation_context)
