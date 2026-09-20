from pathlib import Path

import pytest

from app.agent.policy import AgentPolicy
from app.agent.tools import SaveNoteArgs, ToolContext, ToolRegistry
from app.config import Settings
from app.domain.errors import FilePolicyError, PolicyDeniedError
from app.embeddings.providers import MockEmbeddingProvider
from app.llm.gateway import LLMGateway
from app.llm.providers import MockLLMProvider
from app.rag.answer import RAGAnswerService
from app.rag.indexer import DocumentIndexer
from app.rag.retriever import HybridRetriever
from app.storage.metadata import SQLiteIndex
from app.storage.sessions import SessionStore


def _registry(tmp_path: Path) -> ToolRegistry:
    settings = Settings.from_root(tmp_path)
    repository = SQLiteIndex(settings)
    embedding = MockEmbeddingProvider()
    answerer = RAGAnswerService(HybridRetriever(repository, embedding), LLMGateway(MockLLMProvider()))
    return ToolRegistry(ToolContext(settings, HybridRetriever(repository, embedding), answerer, SessionStore(settings)))


def test_unknown_tool_and_unconfirmed_note_are_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(PolicyDeniedError):
        registry.execute("run_shell", {})
    with pytest.raises(PolicyDeniedError):
        registry.execute(
            "save_note", {"title": "x", "content": "body", "session_id": "session-1"}
        )


def test_confirmed_note_is_exclusive_and_never_overwritten(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    arguments = {
        "title": "UART note",
        "content": "token=hidden",
        "session_id": "session-1234567890",
        "confirmed": True,
    }
    saved = registry.execute("save_note", arguments)
    assert saved["data"]["status"] == "saved"
    note = tmp_path / "data" / "notes" / saved["data"]["path"]
    assert note.read_text(encoding="utf-8") == "token=[REDACTED]"
    repeated = registry.execute("save_note", arguments)
    assert repeated["data"]["status"] == "already_saved"
    assert note.read_text(encoding="utf-8") == "token=[REDACTED]"


def test_policy_limits_steps() -> None:
    policy = AgentPolicy(max_steps=4)
    policy.validate_step(3)
    with pytest.raises(PolicyDeniedError):
        policy.validate_step(4)
