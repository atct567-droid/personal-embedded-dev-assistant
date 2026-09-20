"""FastAPI entrypoint with stable errors, request traces and local services."""

from __future__ import annotations

from dataclasses import asdict
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import AppError
from app.domain.models import (
    AgentConfirmRequest,
    AgentRunRequest,
    AgentStateModel,
    CitationResponse,
    ErrorResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    RAGQueryRequest,
    ScanRequest,
    ScanResponse,
)
from app.logging_config import LOGGER_NAME
from app.runtime import get_runtime


app = FastAPI(title="Personal Embedded Development Assistant", version="0.2.0")
logger = logging.getLogger(LOGGER_NAME)


def new_trace_id() -> str:
    return f"trace-{uuid4().hex}"


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", new_trace_id())


def _error_response(status_code: int, code: str, message: str, trace_id: str) -> JSONResponse:
    response = ErrorResponse(error={"code": code, "message": message}, trace_id=trace_id)
    return JSONResponse(status_code=status_code, content=response.model_dump())


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = new_trace_id()
    request.state.trace_id = trace_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    logger.info(
        "request.completed",
        extra={
            "event": "request.completed",
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
        },
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.public_message, _trace_id(request))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    del exc
    return _error_response(422, "INVALID_REQUEST", "请求参数无效", _trace_id(request))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "METHOD_NOT_ALLOWED" if exc.status_code == 405 else "HTTP_ERROR"
    message = "请求的资源不存在" if exc.status_code == 404 else "请求方法不允许" if exc.status_code == 405 else "HTTP 请求失败"
    return _error_response(exc.status_code, code, message, _trace_id(request))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "request.failed",
        extra={"event": "request.failed", "trace_id": _trace_id(request)},
    )
    del exc
    return _error_response(500, "INTERNAL_ERROR", "服务暂时无法完成请求", _trace_id(request))


def _runtime():
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        runtime = get_runtime()
        app.state.runtime = runtime
    return runtime


@app.get("/health", response_model=HealthResponse)
def health(request: Request):
    trace_id = _trace_id(request)
    try:
        runtime = _runtime()
        runtime.index.document_count()
    except AppError as exc:
        return JSONResponse(
            status_code=503,
            content=HealthResponse(
                status="degraded",
                mode="configured",
                trace_id=trace_id,
                checks={"runtime": exc.public_message},
            ).model_dump(),
        )
    mode = "offline-mock" if not runtime.embedding_is_remote and not runtime.llm_is_remote else "configured"
    return HealthResponse(
        status="ok",
        mode=mode,
        trace_id=trace_id,
        checks={"database": "ok", "providers": "ok"},
    )


@app.post("/v1/documents/ingest", response_model=IngestResponse)
def ingest_document(payload: IngestRequest, request: Request) -> IngestResponse:
    runtime = _runtime()
    trace_id = _trace_id(request)
    result = runtime.imports.ingest_path(
        payload.source_path,
        project_id=payload.project_id,
        allow_external_processing=payload.allow_external_processing,
    )
    runtime.sessions.record_trace(trace_id, "document.ingest", asdict(result))
    return IngestResponse(
        source_file=result.source_file,
        file_hash=result.file_hash,
        status=result.status,
        chunk_count=result.chunk_count,
        trace_id=trace_id,
    )


@app.post("/v1/documents/scan", response_model=ScanResponse)
def scan_documents(payload: ScanRequest, request: Request) -> ScanResponse:
    runtime = _runtime()
    trace_id = _trace_id(request)
    result = runtime.imports.scan(
        project_id=payload.project_id,
        recursive=payload.recursive,
        allow_external_processing=payload.allow_external_processing,
    )
    runtime.sessions.record_trace(
        trace_id,
        "document.scan",
        {key: value for key, value in result.items() if key != "failures"},
    )
    return ScanResponse(**result, trace_id=trace_id)


@app.post("/v1/rag/query", response_model=CitationResponse)
def rag_query(payload: RAGQueryRequest, request: Request) -> CitationResponse:
    runtime = _runtime()
    trace_id = _trace_id(request)
    runtime.sessions.record_trace(trace_id, "rag.query.started", {"project_id": payload.project_id})
    response = runtime.conversations.query(
        payload.question,
        project_id=payload.project_id,
        top_k=payload.top_k,
        trace_id=trace_id,
        session_id=payload.session_id,
        allow_external_processing=payload.allow_external_processing,
    )
    runtime.sessions.record_trace(
        trace_id,
        "rag.query.completed",
        {"citation_count": len(response.citations), "session_id": response.session_id},
    )
    return response


@app.get("/v1/traces/{trace_id}")
def get_trace(trace_id: str, request: Request) -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "request_trace_id": _trace_id(request),
        "events": _runtime().sessions.get_trace(trace_id),
    }


@app.post("/v1/agent/run", response_model=AgentStateModel)
def agent_run(payload: AgentRunRequest, request: Request) -> AgentStateModel:
    runtime = _runtime()
    return runtime.agent.run(
        payload.user_goal,
        project_id=payload.project_id,
        trace_id=_trace_id(request),
        session_id=payload.session_id,
        allow_external_processing=payload.allow_external_processing,
    )


@app.post("/v1/agent/confirm", response_model=AgentStateModel)
def agent_confirm(payload: AgentConfirmRequest, request: Request) -> AgentStateModel:
    return _runtime().agent.confirm(payload.session_id, payload.confirm, trace_id=_trace_id(request))


@app.get("/v1/sessions/{session_id}", response_model=AgentStateModel)
def get_session(session_id: str, request: Request) -> AgentStateModel:
    del request
    return _runtime().sessions.get_state(session_id)
