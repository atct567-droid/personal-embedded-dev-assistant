from pathlib import Path

import pytest

from app.config import Settings
from app.domain.errors import PolicyDeniedError
from app.storage.sessions import SessionStore


def test_session_keeps_ten_turns_and_summarizes_overflow(tmp_path: Path) -> None:
    store = SessionStore(Settings.from_root(tmp_path))
    session_id = store.ensure_session(
        None, project_id="project-a", mode="rag", title="context test"
    )
    for index in range(12):
        store.add_turn(session_id, "user", f"turn-{index}")
    context = store.get_context(session_id)
    assert len(context["turns"]) == 10
    assert "turn-0" in context["summary"]
    assert "turn-1" in context["summary"]


def test_session_cannot_cross_project_or_mode(tmp_path: Path) -> None:
    store = SessionStore(Settings.from_root(tmp_path))
    session_id = store.ensure_session(
        "session-fixed", project_id="project-a", mode="rag", title="project a"
    )
    with pytest.raises(PolicyDeniedError):
        store.ensure_session(
            session_id, project_id="project-b", mode="rag", title="project b"
        )
    with pytest.raises(PolicyDeniedError):
        store.ensure_session(
            session_id, project_id="project-a", mode="agent", title="agent"
        )
