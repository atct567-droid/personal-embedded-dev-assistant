from pathlib import Path

import pytest

from app.config import Settings
from app.domain.models import RAGQueryRequest
from app.security import redact_sensitive, safe_filename


def test_settings_are_project_local(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    assert settings.project_root == tmp_path.resolve()
    assert settings.inbox_dir == tmp_path.resolve() / "data" / "inbox"
    assert settings.max_agent_steps == 4


def test_query_model_rejects_blank_question() -> None:
    with pytest.raises(ValueError):
        RAGQueryRequest(question="   ")


def test_filename_and_secret_redaction() -> None:
    assert safe_filename("../UART log: 2026/09") == "UART-log-2026-09"
    redacted = redact_sensitive("Authorization: Bearer abc123 token=secret-value")
    assert "abc123" not in redacted
    assert "secret-value" not in redacted
    assert "[REDACTED]" in redacted

