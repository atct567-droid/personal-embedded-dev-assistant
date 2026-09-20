"""Runtime configuration and project-local data directories."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


DEFAULT_EXTENSIONS = frozenset({".md", ".txt", ".pdf", ".c", ".h", ".log"})


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _boolean(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated paths and conservative limits for one local installation."""

    project_root: Path
    inbox_dir: Path
    index_dir: Path
    logs_dir: Path
    notes_dir: Path
    database_path: Path
    max_file_bytes: int = 5 * 1024 * 1024
    max_query_chars: int = 1_000
    max_agent_steps: int = 4
    max_tool_retries: int = 1
    tool_timeout_seconds: float = 5.0
    max_log_files: int = 100
    max_log_scan_bytes: int = 20 * 1024 * 1024
    chunk_max_chars: int = 700
    chunk_overlap_chars: int = 100
    allow_remote_models: bool = False
    allowed_extensions: frozenset[str] = DEFAULT_EXTENSIONS

    @classmethod
    def from_root(cls, root: Path) -> "Settings":
        project_root = root.expanduser().resolve()
        data_root = project_root / "data"
        return cls(
            project_root=project_root,
            inbox_dir=data_root / "inbox",
            index_dir=data_root / "index",
            logs_dir=data_root / "logs",
            notes_dir=data_root / "notes",
            database_path=data_root / "assistant.sqlite3",
        )

    @classmethod
    def from_env(cls, default_root: Path | None = None) -> "Settings":
        root_value = os.getenv("PDA_PROJECT_ROOT")
        root = Path(root_value) if root_value else (default_root or Path(__file__).resolve().parent.parent)
        settings = cls.from_root(root)
        return replace(
            settings,
            max_file_bytes=_positive_int(os.getenv("PDA_MAX_FILE_BYTES"), settings.max_file_bytes),
            max_log_files=_positive_int(os.getenv("PDA_MAX_LOG_FILES"), settings.max_log_files),
            max_log_scan_bytes=_positive_int(
                os.getenv("PDA_MAX_LOG_SCAN_BYTES"), settings.max_log_scan_bytes
            ),
            allow_remote_models=_boolean(os.getenv("PDA_ALLOW_REMOTE_MODELS")),
        )

    def ensure_directories(self) -> None:
        """Create only the project-owned runtime directories."""
        for directory in (self.inbox_dir, self.index_dir, self.logs_dir, self.notes_dir):
            directory.mkdir(parents=True, exist_ok=True)
