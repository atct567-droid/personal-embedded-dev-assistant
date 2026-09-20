from pathlib import Path
from dataclasses import replace

from app.config import Settings
from app.embeddings.providers import MockEmbeddingProvider
from app.rag.indexer import DocumentIndexer
from app.storage.metadata import SQLiteIndex


class AlternateEmbeddingProvider:
    dimension = 3
    provider_name = "test"
    model_name = "alternate"
    is_remote = False
    fingerprint = "test:alternate:3"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    def embed_many(self, texts) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class ConfigurableEmbeddingProvider:
    is_remote = False
    provider_name = "test"

    def __init__(self, model_name: str, dimension: int) -> None:
        self.model_name = model_name
        self.dimension = dimension

    @property
    def fingerprint(self) -> str:
        return f"{self.provider_name}:{self.model_name}:{self.dimension}"

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (self.dimension - 1)

    def embed_many(self, texts) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def test_indexer_skips_same_hash_and_replaces_changed_document(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    repository = SQLiteIndex(settings)
    indexer = DocumentIndexer(repository, MockEmbeddingProvider())
    source = tmp_path / "guide.md"
    source.write_text("# UART\nPA9 是 TX。", encoding="utf-8")

    first = indexer.ingest_file(source, relative_path="guide.md")
    second = indexer.ingest_file(source, relative_path="guide.md")
    assert first.status == "indexed"
    assert second.status == "unchanged"
    assert second.chunk_count == first.chunk_count
    assert repository.document_count() == 1
    assert len(repository.list_chunks()) == first.chunk_count

    source.write_text("# UART\nPA10 是 RX。", encoding="utf-8")
    third = indexer.ingest_file(source, relative_path="guide.md")
    assert third.status == "indexed"
    assert third.file_hash != first.file_hash
    assert "PA10" in repository.list_chunks()[0].content


def test_indexer_rebuilds_when_provider_or_chunk_settings_change(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    repository = SQLiteIndex(settings)
    source = tmp_path / "guide.txt"
    source.write_text("UART PA9 TX", encoding="utf-8")
    first = DocumentIndexer(repository, MockEmbeddingProvider(), settings).ingest_file(source)
    switched = DocumentIndexer(repository, AlternateEmbeddingProvider(), settings).ingest_file(source)
    assert switched.status == "indexed"
    assert switched.index_fingerprint != first.index_fingerprint
    assert len(repository.list_chunks()[0].vector) == 3

    changed_settings = replace(settings, chunk_max_chars=600)
    changed = DocumentIndexer(repository, AlternateEmbeddingProvider(), changed_settings).ingest_file(source)
    assert changed.status == "indexed"
    assert changed.index_fingerprint != switched.index_fingerprint


def test_indexer_rebuilds_for_model_dimension_and_chunk_changes_individually(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    repository = SQLiteIndex(settings)
    source = tmp_path / "guide.txt"
    source.write_text("UART PA9 TX", encoding="utf-8")

    first_result = DocumentIndexer(
        repository, ConfigurableEmbeddingProvider("model-a", 4), settings
    ).ingest_file(source)
    model_result = DocumentIndexer(
        repository, ConfigurableEmbeddingProvider("model-b", 4), settings
    ).ingest_file(source)
    dimension_result = DocumentIndexer(
        repository, ConfigurableEmbeddingProvider("model-b", 5), settings
    ).ingest_file(source)
    changed_settings = replace(settings, chunk_max_chars=600)
    chunk_result = DocumentIndexer(
        repository, ConfigurableEmbeddingProvider("model-b", 5), changed_settings
    ).ingest_file(source)

    assert first_result.status == "indexed"
    assert model_result.status == "indexed"
    assert dimension_result.status == "indexed"
    assert chunk_result.status == "indexed"
    assert len(repository.list_chunks()[0].vector) == 5
    assert len({
        first_result.index_fingerprint,
        model_result.index_fingerprint,
        dimension_result.index_fingerprint,
        chunk_result.index_fingerprint,
    }) == 4
