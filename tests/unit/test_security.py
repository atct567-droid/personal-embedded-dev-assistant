from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.errors import FilePolicyError, InvalidInputError, PathPolicyError
from app.embeddings.providers import MockEmbeddingProvider
from app.llm.gateway import LLMGateway
from app.llm.providers import MockLLMProvider
from app.agent.tools import ToolContext, ToolRegistry
from app.rag.answer import RAGAnswerService
from app.rag.retriever import HybridRetriever
from app.security import redact_sensitive, validate_source_path
from app.storage.metadata import SQLiteIndex
from app.storage.sessions import SessionStore


def test_source_path_rejects_traversal_and_unsupported_extension(tmp_path: Path) -> None:
    root = tmp_path / "project"
    settings = Settings.from_root(root)
    settings.ensure_directories()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(PathPolicyError):
        validate_source_path("..\\..\\outside.txt", settings)
    unsupported = settings.inbox_dir / "payload.exe"
    unsupported.write_bytes(b"x")
    with pytest.raises(FilePolicyError):
        validate_source_path("payload.exe", settings)


def test_source_path_rejects_oversized_file(tmp_path: Path) -> None:
    settings = replace(Settings.from_root(tmp_path), max_file_bytes=2)
    settings.ensure_directories()
    source = settings.inbox_dir / "large.txt"
    source.write_text("123", encoding="utf-8")
    with pytest.raises(FilePolicyError):
        validate_source_path("large.txt", settings)


def test_tool_schema_rejects_extra_arguments(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    embeddings = MockEmbeddingProvider()
    repository = SQLiteIndex(settings)
    answerer = RAGAnswerService(HybridRetriever(repository, embeddings), LLMGateway(MockLLMProvider()))
    registry = ToolRegistry(ToolContext(settings, HybridRetriever(repository, embeddings), answerer, SessionStore(settings)))
    with pytest.raises(InvalidInputError):
        registry.execute("search_log", {"query": "ERROR", "unexpected": "value"})


def test_redaction_handles_structured_json_and_quoted_fields() -> None:
    redacted = redact_sensitive('{"token":"abc","nested":{"Authorization":"Bearer xyz"}}')
    assert "abc" not in redacted
    assert "xyz" not in redacted
    quoted = redact_sensitive('prefix "password":"hidden"')
    assert "hidden" not in quoted
