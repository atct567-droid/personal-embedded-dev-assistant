"""Deterministic overlapping text chunking with source metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import DocumentChunk
from app.rag.parser import ParsedDocument


def _window_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("chunk size and overlap are invalid")
    if len(text) <= max_chars:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary_candidates = [text.rfind("\n\n", start, end), text.rfind("\n", start, end), text.rfind(" ", start, end)]
            boundary = max(boundary_candidates)
            if boundary > start + max_chars // 2:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            windows.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return windows


def chunk_document(
    document: ParsedDocument,
    project_id: str = "default",
    max_chars: int = 700,
    overlap: int = 100,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    now = datetime.now(UTC)
    for page in document.pages:
        for content in _window_text(page.content, max_chars, overlap):
            index = len(chunks)
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document.file_hash[:12]}-{index:04d}",
                    project_id=project_id,
                    source_file=document.source_file,
                    relative_path=document.relative_path,
                    document_type=document.document_type,
                    page_number=page.page_number,
                    section_title=page.section_title,
                    chunk_index=index,
                    content=content,
                    file_hash=document.file_hash,
                    updated_at=now,
                    chunk_strategy=document.chunk_strategy,
                )
            )
    return chunks
