"""Safe parsing and normalization for supported local text sources."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.errors import DependencyUnavailableError, FilePolicyError
from app.security import redact_sensitive


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int | None
    section_title: str | None
    content: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_file: str
    relative_path: str
    document_type: str
    file_hash: str
    pages: tuple[ParsedPage, ...]
    chunk_strategy: str = "text-window"


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_C_FUNCTION_RE = re.compile(
    r"^\s*(?:(?:static|inline|extern)\s+)*(?:[A-Za-z_]\w*[\s\*]+)+"
    r"(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*\{"
)


def hash_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = redact_sensitive(text)
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _parse_markdown_sections(text: str) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        content = clean_text("\n".join(current_lines))
        if content:
            pages.append(ParsedPage(None, current_title, content))

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current_title = heading.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return pages or [ParsedPage(None, None, clean_text(text))]


def _parse_pdf(path: Path) -> list[ParsedPage]:
    try:
        import fitz
    except ImportError as exc:
        raise DependencyUnavailableError("文本型 PDF 解析需要安装 PyMuPDF") from exc
    pages: list[ParsedPage] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            content = clean_text(page.get_text("text"))
            if content:
                pages.append(ParsedPage(index, None, content))
    return pages


def _parse_c_sections(text: str) -> tuple[list[ParsedPage], str]:
    lines = text.splitlines()
    pages: list[ParsedPage] = []
    cursor = 0
    index = 0
    while index < len(lines):
        match = _C_FUNCTION_RE.match(lines[index])
        if not match:
            index += 1
            continue
        if index > cursor:
            preamble = clean_text("\n".join(lines[cursor:index]))
            if preamble:
                pages.append(ParsedPage(None, "file-scope", preamble))
        start = index
        balance = 0
        opened = False
        while index < len(lines):
            balance += lines[index].count("{") - lines[index].count("}")
            opened = opened or "{" in lines[index]
            index += 1
            if opened and balance <= 0:
                break
        content = clean_text("\n".join(lines[start:index]))
        if content:
            pages.append(ParsedPage(None, match.group("name"), content))
        cursor = index
    if cursor < len(lines):
        trailing = clean_text("\n".join(lines[cursor:]))
        if trailing:
            pages.append(ParsedPage(None, "file-scope", trailing))
    if not any(page.section_title != "file-scope" for page in pages):
        return [ParsedPage(None, None, clean_text(text))], "text-window-fallback"
    return pages, "c-function"


def parse_document(path: Path, relative_path: str | None = None) -> ParsedDocument:
    if not path.is_file():
        raise FilePolicyError("只允许解析普通文件")
    suffix = path.suffix.lower()
    if suffix not in {".md", ".txt", ".pdf", ".c", ".h", ".log"}:
        raise FilePolicyError("文件类型不在解析器允许列表内")
    file_hash = hash_file(path)
    chunk_strategy = "text-window"
    if suffix == ".pdf":
        pages = _parse_pdf(path)
        chunk_strategy = "pdf-page"
    else:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if suffix == ".md":
            pages = _parse_markdown_sections(text)
            chunk_strategy = "markdown-section"
        elif suffix in {".c", ".h"}:
            pages, chunk_strategy = _parse_c_sections(text)
        else:
            pages = [ParsedPage(None, None, clean_text(text))]
    return ParsedDocument(
        source_file=path.name,
        relative_path=relative_path or path.name,
        document_type=suffix[1:],
        file_hash=file_hash,
        pages=tuple(page for page in pages if page.content),
        chunk_strategy=chunk_strategy,
    )
