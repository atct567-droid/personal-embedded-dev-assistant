"""Application composition root shared by API, UI and offline evaluation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings
from app.agent.policy import AgentPolicy
from app.agent.tools import ToolContext, ToolRegistry
from app.agent.workflow import AgentWorkflow
from app.domain.errors import InvalidInputError
from app.embeddings.providers import MockEmbeddingProvider, OpenAICompatibleEmbeddingProvider
from app.llm.gateway import LLMGateway
from app.llm.providers import MockLLMProvider, OpenAICompatibleProvider
from app.logging_config import configure_logging
from app.rag.answer import RAGAnswerService
from app.rag.indexer import DocumentIndexer
from app.rag.retriever import HybridRetriever
from app.storage.metadata import SQLiteIndex
from app.storage.sessions import SessionStore
from app.services import ImportService, RAGConversationService


@dataclass(slots=True)
class ApplicationRuntime:
    settings: Settings
    index: SQLiteIndex
    indexer: DocumentIndexer
    retriever: HybridRetriever
    answerer: RAGAnswerService
    sessions: SessionStore
    embedding_provider_name: str
    llm_provider_name: str
    embedding_is_remote: bool
    llm_is_remote: bool
    agent: AgentWorkflow
    imports: ImportService
    conversations: RAGConversationService

    @classmethod
    def from_settings(cls, settings: Settings) -> "ApplicationRuntime":
        settings.ensure_directories()
        configure_logging(settings)
        embedding_name = os.getenv("PDA_EMBEDDING_PROVIDER", "mock").lower()
        llm_name = os.getenv("PDA_LLM_PROVIDER", "mock").lower()
        if embedding_name == "mock":
            embedding_provider = MockEmbeddingProvider()
        elif embedding_name in {"openai", "openai-compatible"}:
            if not settings.allow_remote_models:
                raise InvalidInputError("远程模型默认禁用，请显式设置 PDA_ALLOW_REMOTE_MODELS=true")
            try:
                embedding_dimension = int(os.getenv("PDA_OPENAI_EMBEDDING_DIMENSION", "0"))
            except ValueError as exc:
                raise InvalidInputError("Embedding 维度配置无效") from exc
            embedding_provider = OpenAICompatibleEmbeddingProvider(
                base_url=os.getenv("PDA_OPENAI_BASE_URL", ""),
                api_key=os.getenv("PDA_OPENAI_API_KEY", ""),
                model=os.getenv("PDA_OPENAI_EMBEDDING_MODEL", ""),
                dimension=embedding_dimension,
            )
            if (
                not embedding_provider.base_url
                or not embedding_provider.api_key
                or not embedding_provider.model
                or embedding_provider.dimension <= 0
            ):
                raise InvalidInputError("真实 Embedding provider 缺少必要配置")
        else:
            raise InvalidInputError("不支持的 Embedding provider")
        if llm_name == "mock":
            llm_provider = MockLLMProvider()
        elif llm_name in {"openai", "openai-compatible"}:
            if not settings.allow_remote_models:
                raise InvalidInputError("远程模型默认禁用，请显式设置 PDA_ALLOW_REMOTE_MODELS=true")
            llm_provider = OpenAICompatibleProvider(
                base_url=os.getenv("PDA_OPENAI_BASE_URL", ""),
                api_key=os.getenv("PDA_OPENAI_API_KEY", ""),
                model=os.getenv("PDA_OPENAI_MODEL", ""),
            )
            if not llm_provider.base_url or not llm_provider.api_key or not llm_provider.model:
                raise InvalidInputError("真实 LLM provider 缺少必要配置")
        else:
            raise InvalidInputError("不支持的 LLM provider")
        index = SQLiteIndex(settings)
        indexer = DocumentIndexer(index, embedding_provider, settings)
        retriever = HybridRetriever(index, embedding_provider)
        sessions = SessionStore(settings)
        answerer = RAGAnswerService(retriever, LLMGateway(llm_provider))
        registry = ToolRegistry(
            ToolContext(settings=settings, retriever=retriever, answerer=answerer, sessions=sessions),
            AgentPolicy(
                max_steps=settings.max_agent_steps,
                max_retries=settings.max_tool_retries,
                timeout_seconds=settings.tool_timeout_seconds,
            ),
        )
        return cls(
            settings=settings,
            index=index,
            indexer=indexer,
            retriever=retriever,
            answerer=answerer,
            sessions=sessions,
            embedding_provider_name=embedding_name,
            llm_provider_name=llm_name,
            embedding_is_remote=embedding_provider.is_remote,
            llm_is_remote=llm_provider.is_remote,
            agent=AgentWorkflow(registry, sessions, registry.policy),
            imports=ImportService(settings, indexer),
            conversations=RAGConversationService(answerer, sessions),
        )


@lru_cache(maxsize=1)
def get_runtime() -> ApplicationRuntime:
    return ApplicationRuntime.from_settings(Settings.from_env())
