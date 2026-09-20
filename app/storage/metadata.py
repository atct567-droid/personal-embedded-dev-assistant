"""SQLite persistence for documents, chunks and local vectors."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.config import Settings
from app.domain.errors import StorageError
from app.domain.models import DocumentChunk
from app.rag.parser import ParsedDocument


class SQLiteIndex:
    """Small transactional repository for the local RAG index."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS documents (
                        project_id TEXT NOT NULL,
                        relative_path TEXT NOT NULL,
                        source_file TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        file_hash TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        chunk_count INTEGER NOT NULL,
                        index_fingerprint TEXT NOT NULL DEFAULT '',
                        embedding_provider TEXT NOT NULL DEFAULT '',
                        embedding_model TEXT NOT NULL DEFAULT '',
                        embedding_dimension INTEGER NOT NULL DEFAULT 0,
                        external_allowed INTEGER NOT NULL DEFAULT 0,
                        chunk_strategy TEXT NOT NULL DEFAULT 'text-window',
                        PRIMARY KEY (project_id, relative_path)
                    );
                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        relative_path TEXT NOT NULL,
                        source_file TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        page_number INTEGER,
                        section_title TEXT,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        file_hash TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        vector_json TEXT NOT NULL,
                        index_fingerprint TEXT NOT NULL DEFAULT '',
                        external_allowed INTEGER NOT NULL DEFAULT 0,
                        FOREIGN KEY (project_id, relative_path)
                            REFERENCES documents(project_id, relative_path)
                            ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_chunks_project
                        ON chunks(project_id, chunk_index);
                    """
                )
                self._ensure_column(connection, "documents", "index_fingerprint", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, "documents", "embedding_provider", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, "documents", "embedding_model", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, "documents", "embedding_dimension", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(connection, "documents", "external_allowed", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(connection, "chunks", "index_fingerprint", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, "chunks", "external_allowed", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(
                    connection,
                    "chunks",
                    "chunk_strategy",
                    "TEXT NOT NULL DEFAULT 'text-window'",
                )
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', '2') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_document(self, project_id: str, relative_path: str) -> sqlite3.Row | None:
        try:
            with closing(self._connect()) as connection, connection:
                return connection.execute(
                    "SELECT * FROM documents WHERE project_id = ? AND relative_path = ?",
                    (project_id, relative_path),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError() from exc

    def replace_document(
        self,
        document: ParsedDocument,
        chunks: list[DocumentChunk],
        *,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
    ) -> None:
        if not chunks:
            raise StorageError("文档没有可索引的文本内容")
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "DELETE FROM chunks WHERE project_id = ? AND relative_path = ?",
                    (chunks[0].project_id, document.relative_path),
                )
                connection.execute(
                    """
                    INSERT INTO documents
                        (project_id, relative_path, source_file, document_type,
                         file_hash, updated_at, chunk_count, index_fingerprint,
                         embedding_provider, embedding_model, embedding_dimension,
                         external_allowed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, relative_path) DO UPDATE SET
                        source_file = excluded.source_file,
                        document_type = excluded.document_type,
                        file_hash = excluded.file_hash,
                        updated_at = excluded.updated_at,
                        chunk_count = excluded.chunk_count,
                        index_fingerprint = excluded.index_fingerprint,
                        embedding_provider = excluded.embedding_provider,
                        embedding_model = excluded.embedding_model,
                        embedding_dimension = excluded.embedding_dimension,
                        external_allowed = excluded.external_allowed
                    """,
                    (
                        chunks[0].project_id,
                        document.relative_path,
                        document.source_file,
                        document.document_type,
                        document.file_hash,
                        chunks[0].updated_at.isoformat(),
                        len(chunks),
                        chunks[0].index_fingerprint,
                        embedding_provider,
                        embedding_model,
                        embedding_dimension,
                        int(chunks[0].external_allowed),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO chunks
                        (chunk_id, project_id, relative_path, source_file,
                         document_type, page_number, section_title, chunk_index,
                         content, file_hash, updated_at, vector_json,
                         index_fingerprint, external_allowed, chunk_strategy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.project_id,
                            chunk.relative_path,
                            chunk.source_file,
                            chunk.document_type,
                            chunk.page_number,
                            chunk.section_title,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.file_hash,
                            chunk.updated_at.isoformat(),
                            json.dumps(chunk.vector, ensure_ascii=False),
                            chunk.index_fingerprint,
                            int(chunk.external_allowed),
                            chunk.chunk_strategy,
                        )
                        for chunk in chunks
                    ],
                )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    def list_chunks(self, project_id: str = "default") -> list[DocumentChunk]:
        try:
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    "SELECT * FROM chunks WHERE project_id = ? ORDER BY relative_path, chunk_index",
                    (project_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError() from exc
        return [
            DocumentChunk(
                chunk_id=row["chunk_id"],
                project_id=row["project_id"],
                source_file=row["source_file"],
                relative_path=row["relative_path"],
                document_type=row["document_type"],
                page_number=row["page_number"],
                section_title=row["section_title"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                file_hash=row["file_hash"],
                updated_at=row["updated_at"],
                vector=json.loads(row["vector_json"]),
                index_fingerprint=row["index_fingerprint"],
                external_allowed=bool(row["external_allowed"]),
                chunk_strategy=row["chunk_strategy"],
            )
            for row in rows
        ]

    def document_count(self, project_id: str = "default") -> int:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM documents WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                return int(row["count"])
        except sqlite3.Error as exc:
            raise StorageError() from exc
