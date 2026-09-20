from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.errors import FilePolicyError, PolicyDeniedError
from app.runtime import ApplicationRuntime


def test_shared_upload_rejects_oversize_before_writing(tmp_path: Path) -> None:
    settings = replace(Settings.from_root(tmp_path), max_file_bytes=2)
    runtime = ApplicationRuntime.from_settings(settings)
    with pytest.raises(FilePolicyError):
        runtime.imports.save_upload_and_ingest("large.txt", b"123")
    assert not (settings.inbox_dir / "large.txt").exists()


def test_scan_indexes_nested_files_and_reports_invalid_files(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    settings.ensure_directories()
    nested = settings.inbox_dir / "nested"
    nested.mkdir()
    (nested / "uart.md").write_text("# UART\nPA9 TX", encoding="utf-8")
    (settings.inbox_dir / "bad.exe").write_bytes(b"x")
    runtime = ApplicationRuntime.from_settings(settings)
    result = runtime.imports.scan(project_id="demo")
    assert result["indexed"] == 1
    assert result["failed"] == 1
    assert result["failures"][0]["relative_path"] == "bad.exe"


def test_rag_context_is_project_isolated_and_supports_follow_up(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    settings.ensure_directories()
    source = settings.inbox_dir / "uart.md"
    source.write_text("# UART\nPA9 作为 TX。", encoding="utf-8")
    runtime = ApplicationRuntime.from_settings(settings)
    runtime.imports.ingest_path("uart.md", project_id="project-a")
    first = runtime.conversations.query(
        "PA9 在 UART 中是什么？",
        project_id="project-a",
        top_k=5,
        trace_id="trace-first",
    )
    second = runtime.conversations.query(
        "它承担什么角色？",
        project_id="project-a",
        top_k=5,
        trace_id="trace-second",
        session_id=first.session_id,
    )
    assert second.citations
    with pytest.raises(PolicyDeniedError):
        runtime.conversations.query(
            "PA9 是什么？",
            project_id="project-b",
            top_k=5,
            trace_id="trace-third",
            session_id=first.session_id,
        )
