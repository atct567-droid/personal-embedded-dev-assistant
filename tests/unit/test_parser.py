from pathlib import Path

from app.rag.chunker import chunk_document
from app.rag.parser import hash_file, parse_document


def test_markdown_sections_are_preserved_and_secrets_redacted(tmp_path: Path) -> None:
    source = tmp_path / "uart.md"
    source.write_text(
        "# UART 初始化\nPA9 作为 TX。\n\n## 安全\ntoken=do-not-store\n",
        encoding="utf-8",
    )
    document = parse_document(source, "uart.md")
    assert document.document_type == "md"
    assert len(document.pages) == 2
    assert document.pages[0].section_title == "UART 初始化"
    assert "do-not-store" not in document.pages[1].content


def test_chunking_keeps_metadata_and_overlap(tmp_path: Path) -> None:
    source = tmp_path / "long.txt"
    source.write_text("0123456789" * 150, encoding="utf-8")
    document = parse_document(source)
    chunks = chunk_document(document, max_chars=100, overlap=20)
    assert len(chunks) > 1
    assert all(chunk.file_hash == document.file_hash for chunk in chunks)
    assert all(chunk.relative_path == "long.txt" for chunk in chunks)
    assert chunks[0].content[-10:] in chunks[1].content


def test_file_hash_changes_only_when_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("one", encoding="utf-8")
    first = hash_file(source)
    source.write_text("two", encoding="utf-8")
    second = hash_file(source)
    assert first != second


def test_text_pdf_is_parsed_with_page_metadata(tmp_path: Path) -> None:
    import fitz

    source = tmp_path / "sensor.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "SHT30 address 0x44")
    source.write_bytes(pdf.tobytes())
    pdf.close()
    document = parse_document(source)
    assert document.document_type == "pdf"
    assert document.pages[0].page_number == 1
    assert "0x44" in document.pages[0].content


def test_c_source_prefers_function_sections_and_falls_back(tmp_path: Path) -> None:
    source = tmp_path / "driver.c"
    source.write_text(
        "#include <stdint.h>\n\nstatic void uart_init(void) {\n  int x = 1;\n}\n",
        encoding="utf-8",
    )
    parsed = parse_document(source)
    assert parsed.chunk_strategy == "c-function"
    assert any(page.section_title == "uart_init" for page in parsed.pages)

    header = tmp_path / "types.h"
    header.write_text("#define UART_BAUD 115200\n", encoding="utf-8")
    fallback = parse_document(header)
    assert fallback.chunk_strategy == "text-window-fallback"
