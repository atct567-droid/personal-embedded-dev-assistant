"""Allow-listed, parameter-validated read tools and confirmed note writing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from app.agent.policy import ALLOWED_TOOLS, AgentPolicy
from app.config import Settings
from app.domain.errors import (
    FilePolicyError,
    InvalidInputError,
    PolicyDeniedError,
    ToolTimeoutError,
)
from app.domain.models import Citation, ChecklistItem, LogEvidence, RetrievalEvidence
from app.rag.answer import RAGAnswerService
from app.rag.retriever import HybridRetriever, has_lexical_overlap
from app.security import redact_sensitive, resolve_inside, safe_filename, validate_source_path
from app.storage.sessions import SessionStore


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    project_id: str = Field(default="default", min_length=1, max_length=80)
    top_k: int = Field(default=5, ge=1, le=10)


class SearchLogArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    relative_path: str | None = Field(default=None, max_length=500)
    max_matches: int = Field(default=20, ge=1, le=50)


class GenerateChecklistArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_goal: str = Field(min_length=1, max_length=1_000)
    evidence: list[RetrievalEvidence] = Field(default_factory=list, max_length=10)
    log_evidence: list[LogEvidence] = Field(default_factory=list, max_length=50)


class SaveNoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=50_000)
    session_id: str = Field(min_length=1, max_length=100)
    confirmed: bool = False


@dataclass(slots=True)
class ToolContext:
    settings: Settings
    retriever: HybridRetriever
    answerer: RAGAnswerService
    sessions: SessionStore
    deadline_monotonic: float | None = None


def _check_deadline(context: ToolContext) -> None:
    if context.deadline_monotonic is not None and monotonic() >= context.deadline_monotonic:
        raise ToolTimeoutError()


def search_knowledge(args: SearchKnowledgeArgs, context: ToolContext) -> dict[str, Any]:
    _check_deadline(context)
    evidence = [
        item
        for item in context.retriever.search(args.question, args.project_id, args.top_k)
        if item.bm25_score > 0.0
        and has_lexical_overlap(args.question, f"{item.section_title or ''}\n{item.content}")
    ]
    _check_deadline(context)
    return {
        "question": args.question,
        "evidence": [item.model_dump() for item in evidence],
        "citations": [
            Citation(
                source_file=item.source_file,
                section=item.section_title,
                page=item.page_number,
                chunk_id=item.chunk_id,
                score=max(0.0, min(1.0, item.score)),
            ).model_dump()
            for item in evidence
        ],
    }


def search_log(args: SearchLogArgs, context: ToolContext) -> dict[str, Any]:
    root = context.settings.logs_dir
    candidates: list[Path]
    if args.relative_path:
        candidates = [validate_source_path(args.relative_path, context.settings, logs=True)]
    else:
        candidates = []
        for candidate in root.rglob("*"):
            _check_deadline(context)
            if len(candidates) >= context.settings.max_log_files:
                break
            if not candidate.is_file():
                continue
            try:
                candidates.append(validate_source_path(candidate.as_posix(), context.settings, logs=True))
            except FilePolicyError:
                continue
    matches: list[dict[str, Any]] = []
    needle = args.query.casefold()
    scanned_bytes = 0
    for path in candidates:
        _check_deadline(context)
        scanned_bytes += path.stat().st_size
        if scanned_bytes > context.settings.max_log_scan_bytes:
            break
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                _check_deadline(context)
                if needle in raw_line.casefold():
                    relative_path = path.relative_to(root).as_posix()
                    item = LogEvidence(
                        evidence_id=f"log:{relative_path}:L{line_number}",
                        source_file=path.name,
                        relative_path=relative_path,
                        line_number=line_number,
                        content=redact_sensitive(raw_line.strip()),
                    )
                    matches.append(item.model_dump())
                    if len(matches) >= args.max_matches:
                        return {
                            "query": args.query,
                            "matches": matches,
                            "scanned_bytes": scanned_bytes,
                        }
    return {"query": args.query, "matches": matches, "scanned_bytes": scanned_bytes}


def generate_checklist(args: GenerateChecklistArgs, context: ToolContext) -> dict[str, Any]:
    _check_deadline(context)
    checklist: list[ChecklistItem] = []
    evidence = args.evidence
    log_evidence = args.log_evidence
    if not evidence and not log_evidence:
        checklist.append(
            ChecklistItem(
                check_object="现有知识资料",
                method="补充与目标相关的文档或日志",
                normal="至少有一条可引用证据",
                next_step="在证据补充前不要把假设当作结论",
                citations=[],
            )
        )
    else:
        for item in evidence[:3]:
            checklist.append(
                ChecklistItem(
                    check_object=item.section_title or item.source_file,
                    method=f"核对资料片段：{item.content[:160]}",
                    normal="现场表现与资料描述一致",
                    next_step="若不一致，记录差异并检查相邻初始化/配置步骤",
                    citations=[
                        Citation(
                            source_file=item.source_file,
                            section=item.section_title,
                            page=item.page_number,
                            chunk_id=item.chunk_id,
                            score=max(0.0, min(1.0, item.score)),
                        )
                    ],
                )
            )
        for item in log_evidence[: max(0, 4 - len(checklist))]:
            checklist.append(
                ChecklistItem(
                    check_object=f"日志 {item.source_file} 第 {item.line_number} 行",
                    method=f"核对日志上下文：{item.content[:160]}",
                    normal="日志中不再出现相同错误，或错误后存在明确恢复记录",
                    next_step="保留原始时间点并关联检查知识库中的对应配置",
                    citations=[
                        Citation(
                            source_file=item.source_file,
                            section=f"line {item.line_number}",
                            page=None,
                            chunk_id=item.evidence_id,
                            score=1.0,
                        )
                    ],
                )
            )
    return {
        "user_goal": args.user_goal,
        "checklist": [item.model_dump() for item in checklist],
    }


def save_note(args: SaveNoteArgs, context: ToolContext) -> dict[str, Any]:
    if not args.confirmed:
        raise PolicyDeniedError("保存笔记必须经过用户明确确认")
    context.settings.notes_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(args.title)}-{safe_filename(args.session_id)[-12:]}.md"
    path = resolve_inside(context.settings.notes_dir / filename, context.settings.notes_dir)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(redact_sensitive(args.content))
    except FileExistsError:
        return {
            "path": path.relative_to(context.settings.notes_dir).as_posix(),
            "status": "already_saved",
        }
    return {"path": path.relative_to(context.settings.notes_dir).as_posix(), "status": "saved"}


class ToolRegistry:
    """Dispatch only to explicitly registered tool handlers."""

    def __init__(self, context: ToolContext, policy: AgentPolicy | None = None) -> None:
        self.context = context
        self.policy = policy or AgentPolicy()
        self._schemas: dict[str, type[BaseModel]] = {
            "search_knowledge": SearchKnowledgeArgs,
            "search_log": SearchLogArgs,
            "generate_checklist": GenerateChecklistArgs,
            "save_note": SaveNoteArgs,
        }
        self._handlers: dict[str, Callable[[Any, ToolContext], dict[str, Any]]] = {
            "search_knowledge": search_knowledge,
            "search_log": search_log,
            "generate_checklist": generate_checklist,
            "save_note": save_note,
        }

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        self.policy.validate_tool(tool_name)
        if tool_name not in ALLOWED_TOOLS or tool_name not in self._handlers:
            raise PolicyDeniedError("工具未注册")
        try:
            parsed = self._schemas[tool_name].model_validate(arguments)
        except Exception as exc:
            raise InvalidInputError("工具参数无效") from exc
        execution_context = replace(self.context, deadline_monotonic=deadline_monotonic)
        data = self._handlers[tool_name](parsed, execution_context)
        return {"tool": tool_name, "ok": True, "data": data}
