from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.errors import PolicyDeniedError
from app.rag.indexer import DocumentIndexer
from app.storage.metadata import SQLiteIndex


class RemoteEmbeddingProvider:
    dimension = 3
    provider_name = "remote-test"
    model_name = "fake"
    is_remote = True
    fingerprint = "remote-test:fake:3"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    def embed_many(self, texts) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def test_remote_embedding_requires_global_and_per_request_authorization(tmp_path: Path) -> None:
    source = tmp_path / "doc.txt"
    source.write_text("safe synthetic text", encoding="utf-8")
    disabled = Settings.from_root(tmp_path)
    repository = SQLiteIndex(disabled)
    with pytest.raises(PolicyDeniedError):
        DocumentIndexer(repository, RemoteEmbeddingProvider(), disabled).ingest_file(
            source, allow_external_processing=True
        )

    enabled = replace(disabled, allow_remote_models=True)
    with pytest.raises(PolicyDeniedError):
        DocumentIndexer(repository, RemoteEmbeddingProvider(), enabled).ingest_file(source)
    result = DocumentIndexer(repository, RemoteEmbeddingProvider(), enabled).ingest_file(
        source, allow_external_processing=True
    )
    assert result.status == "indexed"
    assert repository.list_chunks()[0].external_allowed is True
