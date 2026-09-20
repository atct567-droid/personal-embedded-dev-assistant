"""Path, file-size and filename policy helpers."""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.errors import FilePolicyError, PathPolicyError


def resolve_inside(candidate: Path, allowed_root: Path, *, must_exist: bool = False) -> Path:
    """Resolve a path and reject traversal outside the configured root."""
    try:
        resolved = candidate.expanduser().resolve(strict=must_exist)
        root = allowed_root.expanduser().resolve()
    except OSError as exc:
        raise PathPolicyError("路径无法解析") from exc
    if resolved != root and root not in resolved.parents:
        raise PathPolicyError()
    return resolved


def validate_source_path(raw_path: str, settings: Settings, *, logs: bool = False) -> Path:
    root = settings.logs_dir if logs else settings.inbox_dir
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = resolve_inside(candidate, root, must_exist=True)
    if not resolved.is_file():
        raise FilePolicyError("只允许读取普通文件")
    if resolved.suffix.lower() not in settings.allowed_extensions:
        raise FilePolicyError("文件类型不在允许列表内")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise FilePolicyError("无法读取文件信息") from exc
    if size > settings.max_file_bytes:
        raise FilePolicyError("文件超过大小限制")
    return resolved


def safe_filename(value: str, fallback: str = "note") -> str:
    """Return a single conservative filename stem without path separators."""
    stem = value.replace("\\", "-").replace("/", "-")
    stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", stem).strip("-._")
    return stem[:80] or fallback


def redact_sensitive(text: str) -> str:
    """Mask common secret-bearing log fields before storage or display."""
    sensitive_keys = {"authorization", "token", "password", "passwd", "api_key", "api-key", "secret"}

    def redact_json(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if str(key).lower() in sensitive_keys else redact_json(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact_json(item) for item in value]
        return value

    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            return json.dumps(redact_json(parsed), ensure_ascii=False, separators=(",", ":"))
    patterns = (
        r"(?i)([\"']?authorization[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\"'\s,;}]+",
        r"(?i)([\"']?(?:token|password|passwd|api[_-]?key|secret)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;}]+",
    )
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, r"\1[REDACTED]", redacted)
    return redacted
