"""Shared application services used by API and Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.errors import AppError, FilePolicyError
from app.domain.models import CitationResponse
from app.rag.answer import RAGAnswerService
from app.rag.indexer import DocumentIndexer, IngestResult
from app.security import resolve_inside, safe_filename, validate_source_path
from app.storage.sessions import SessionStore


@dataclass(slots=True)
class ImportService:
    settings: Settings
    indexer: DocumentIndexer

    def ingest_path(
        self,
        raw_path: str,
        *,
        project_id: str = "default",
        allow_external_processing: bool = False,
    ) -> IngestResult:
        path = validate_source_path(raw_path, self.settings)
        relative_path = path.relative_to(self.settings.inbox_dir).as_posix()
        return self.indexer.ingest_file(
            path,
            project_id=project_id,
            relative_path=relative_path,
            allow_external_processing=allow_external_processing,
        )

    def save_upload_and_ingest(
        self,
        filename: str,
        content: bytes,
        *,
        project_id: str = "default",
        allow_external_processing: bool = False,
    ) -> IngestResult:
        original = Path(filename)
        suffix = original.suffix.lower()
        if suffix not in self.settings.allowed_extensions:
            raise FilePolicyError("文件类型不在允许列表内")
        if len(content) > self.settings.max_file_bytes:
            raise FilePolicyError("文件超过大小限制")
        safe_name = safe_filename(original.stem, fallback="uploaded") + suffix
        target = resolve_inside(self.settings.inbox_dir / safe_name, self.settings.inbox_dir)
        try:
            with target.open("xb") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise FilePolicyError("同名文件已存在，不会覆盖") from exc
        return self.ingest_path(
            safe_name,
            project_id=project_id,
            allow_external_processing=allow_external_processing,
        )

    def scan(
        self,
        *,
        project_id: str = "default",
        recursive: bool = True,
        allow_external_processing: bool = False,
    ) -> dict[str, Any]:
        iterator = self.settings.inbox_dir.rglob("*") if recursive else self.settings.inbox_dir.glob("*")
        indexed = unchanged = 0
        failures: list[dict[str, str]] = []
        for candidate in iterator:
            if not candidate.is_file() or candidate.name == ".gitkeep":
                continue
            relative_path = candidate.relative_to(self.settings.inbox_dir).as_posix()
            try:
                result = self.ingest_path(
                    relative_path,
                    project_id=project_id,
                    allow_external_processing=allow_external_processing,
                )
                if result.status == "indexed":
                    indexed += 1
                else:
                    unchanged += 1
            except AppError as exc:
                failures.append({"relative_path": relative_path, "error": exc.public_message})
        return {
            "project_id": project_id,
            "indexed": indexed,
            "unchanged": unchanged,
            "failed": len(failures),
            "failures": failures,
        }


@dataclass(slots=True)
class RAGConversationService:
    answerer: RAGAnswerService
    sessions: SessionStore

    @staticmethod
    def _format_context(context: dict[str, Any]) -> tuple[str, str]:
        turns = context["turns"]
        recent = "\n".join(
            f"{item['role']}: {item['content']}" for item in turns[-6:]
        )
        conversation = "\n".join(
            part for part in (context["summary"], recent) if part
        )
        retrieval = "\n".join(
            item["content"] for item in turns if item["role"] == "user"
        )[-1000:]
        return conversation, retrieval

    def query(
        self,
        question: str,
        *,
        project_id: str,
        top_k: int,
        trace_id: str,
        session_id: str | None = None,
        allow_external_processing: bool = False,
    ) -> CitationResponse:
        resolved_session = self.sessions.ensure_session(
            session_id,
            project_id=project_id,
            mode="rag",
            title=question,
        )
        context = self.sessions.get_context(resolved_session)
        conversation, retrieval = self._format_context(context)
        response = self.answerer.answer(
            question,
            project_id=project_id,
            top_k=top_k,
            trace_id=trace_id,
            session_id=resolved_session,
            conversation_context=conversation,
            retrieval_context=retrieval,
            allow_external_processing=allow_external_processing,
        )
        self.sessions.add_turn(resolved_session, "user", question)
        self.sessions.add_turn(resolved_session, "assistant", response.answer)
        return response
