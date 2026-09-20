"""Incremental document ingestion into the local SQLite index."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.domain.errors import PolicyDeniedError, StorageError
from app.embeddings.gateway import EmbeddingProvider
from app.rag.chunker import chunk_document
from app.rag.parser import ParsedDocument, parse_document
from app.storage.metadata import SQLiteIndex


@dataclass(frozen=True, slots=True)
class IngestResult:
    source_file: str
    relative_path: str
    file_hash: str
    status: str
    chunk_count: int
    index_fingerprint: str
    external_allowed: bool


PARSER_VERSION = "parser-v2"


class DocumentIndexer:
    def __init__(
        self,
        repository: SQLiteIndex,
        embedding_provider: EmbeddingProvider,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.settings = settings or repository.settings

    @property
    def index_fingerprint(self) -> str:
        payload = (
            f"{self.embedding_provider.fingerprint}|{PARSER_VERSION}|"
            f"chunk={self.settings.chunk_max_chars}|overlap={self.settings.chunk_overlap_chars}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def ingest_file(
        self,
        path: Path,
        project_id: str = "default",
        relative_path: str | None = None,
        allow_external_processing: bool = False,
    ) -> IngestResult:
        if self.embedding_provider.is_remote and (
            not self.settings.allow_remote_models or not allow_external_processing
        ):
            raise PolicyDeniedError("远程 Embedding 需要全局开关和本次导入双重授权")
        document = parse_document(path, relative_path)
        fingerprint = self.index_fingerprint
        stored = self.repository.get_document(project_id, document.relative_path)
        if (
            stored is not None
            and stored["file_hash"] == document.file_hash
            and stored["index_fingerprint"] == fingerprint
            and bool(stored["external_allowed"]) == allow_external_processing
        ):
            return IngestResult(
                source_file=document.source_file,
                relative_path=document.relative_path,
                file_hash=document.file_hash,
                status="unchanged",
                chunk_count=int(stored["chunk_count"]),
                index_fingerprint=fingerprint,
                external_allowed=allow_external_processing,
            )
        chunks = chunk_document(
            document,
            project_id=project_id,
            max_chars=self.settings.chunk_max_chars,
            overlap=self.settings.chunk_overlap_chars,
        )
        vectors = self.embedding_provider.embed_many([chunk.content for chunk in chunks])
        if any(len(vector) != self.embedding_provider.dimension for vector in vectors):
            raise StorageError("Embedding 返回的向量维度与配置不一致")
        indexed_chunks = [
            chunk.model_copy(
                update={
                    "vector": vector,
                    "index_fingerprint": fingerprint,
                    "external_allowed": allow_external_processing,
                }
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.repository.replace_document(
            document,
            indexed_chunks,
            embedding_provider=self.embedding_provider.provider_name,
            embedding_model=self.embedding_provider.model_name,
            embedding_dimension=self.embedding_provider.dimension,
        )
        return IngestResult(
            source_file=document.source_file,
            relative_path=document.relative_path,
            file_hash=document.file_hash,
            status="indexed",
            chunk_count=len(indexed_chunks),
            index_fingerprint=fingerprint,
            external_allowed=allow_external_processing,
        )
