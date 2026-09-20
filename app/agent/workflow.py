"""Bounded troubleshooting workflow with explicit state and confirmation."""

from __future__ import annotations

from time import monotonic
from uuid import uuid4

from app.agent.policy import AgentPolicy
from app.agent.state import new_state
from app.agent.tools import ToolRegistry
from app.domain.models import AgentStateModel, LogEvidence, RetrievalEvidence
from app.storage.sessions import SessionStore


class AgentWorkflow:
    def __init__(self, registry: ToolRegistry, sessions: SessionStore, policy: AgentPolicy | None = None) -> None:
        self.registry = registry
        self.sessions = sessions
        self.policy = policy or AgentPolicy()

    def _execute_tool(self, tool_name: str, arguments: dict[str, object], trace_id: str) -> dict[str, object]:
        self.policy.validate_tool(tool_name)
        last_error = "工具执行失败"
        attempts = 0
        retry_count = 0 if tool_name == "save_note" else self.policy.max_retries
        for attempt in range(retry_count + 1):
            attempts = attempt + 1
            try:
                result = self.registry.execute(
                    tool_name,
                    arguments,
                    deadline_monotonic=monotonic() + self.policy.timeout_seconds,
                )
                self.sessions.record_trace(
                    trace_id,
                    "agent.tool.completed",
                    {"tool": tool_name, "attempts": attempts, "ok": True},
                )
                return result
            except Exception as exc:
                last_error = getattr(exc, "public_message", "工具执行失败")
            if attempt < retry_count:
                self.sessions.record_trace(
                    trace_id,
                    "agent.tool.retry",
                    {"tool": tool_name, "attempt": attempts, "reason": last_error},
                )
        return {"tool": tool_name, "ok": False, "error": last_error, "attempts": attempts}

    @staticmethod
    def _log_query(user_goal: str) -> str:
        lowered = user_goal.casefold()
        for marker in (
            "watchdog reset",
            "error",
            "fail",
            "timeout",
            "异常",
            "错误",
            "超时",
        ):
            if marker in lowered:
                return marker
        return user_goal[:80]

    @staticmethod
    def _format_context(context: dict[str, object]) -> str:
        turns = context.get("turns", [])
        recent = "\n".join(
            f"{item['role']}: {item['content']}" for item in turns[-6:]
        )
        return "\n".join(
            part for part in (str(context.get("summary", "")), recent) if part
        )

    def run(
        self,
        user_goal: str,
        project_id: str = "default",
        trace_id: str | None = None,
        session_id: str | None = None,
        allow_external_processing: bool = False,
    ) -> AgentStateModel:
        trace_id = trace_id or f"trace-{uuid4().hex}"
        resolved_session = self.sessions.ensure_session(
            session_id,
            project_id=project_id,
            mode="agent",
            title=user_goal,
        )
        context = self.sessions.get_context(resolved_session)
        state = new_state(resolved_session, trace_id, user_goal, project_id)
        state.summary = str(context["summary"])
        self.sessions.record_trace(trace_id, "agent.started", {"project_id": project_id})
        evidence: list[RetrievalEvidence] = []
        log_evidence: list[LogEvidence] = []

        planned_calls = [
            ("search_knowledge", {"question": user_goal, "project_id": project_id, "top_k": 5}),
            ("search_log", {"query": self._log_query(user_goal), "max_matches": 20}),
        ]
        for tool_name, arguments in planned_calls:
            self.policy.validate_step(len(state.completed_steps))
            result = self._execute_tool(tool_name, arguments, trace_id)
            state.tool_results.append(result)
            state.completed_steps.append(tool_name)
            if tool_name == "search_knowledge" and result.get("ok"):
                evidence = [RetrievalEvidence.model_validate(item) for item in result["data"].get("evidence", [])]
                state.retrieved_evidence = evidence
            if tool_name == "search_log" and result.get("ok"):
                log_evidence = [
                    LogEvidence.model_validate(item)
                    for item in result["data"].get("matches", [])
                ]
                state.log_evidence = log_evidence
            if not result.get("ok"):
                state.error = str(result.get("error", "工具执行失败"))

        self.policy.validate_step(len(state.completed_steps))
        checklist_result = self._execute_tool(
            "generate_checklist",
            {
                "user_goal": user_goal,
                "evidence": [item.model_dump() for item in evidence],
                "log_evidence": [item.model_dump() for item in log_evidence],
            },
            trace_id,
        )
        state.tool_results.append(checklist_result)
        state.completed_steps.append("generate_checklist")
        if checklist_result.get("ok"):
            checklist = checklist_result["data"].get("checklist", [])
        else:
            checklist = []
            state.error = str(checklist_result.get("error", "排查清单生成失败"))

        state.final_answer = self.registry.context.answerer.answer_from_evidence(
            user_goal,
            evidence,
            conversation_context=self._format_context(context),
            allow_external_processing=allow_external_processing,
        )
        if log_evidence:
            state.final_answer += "\n\n日志证据：\n" + "\n".join(
                f"- [{item.evidence_id}] {item.content}" for item in log_evidence[:5]
            )
        if checklist:
            state.final_answer += "\n\n排查清单：\n" + "\n".join(
                f"{index}. {item['check_object']}：{item['method']}；正常表现：{item['normal']}；"
                f"异常后：{item['next_step']}；证据："
                f"{', '.join(citation['chunk_id'] for citation in item['citations']) or '无'}"
                for index, item in enumerate(checklist, start=1)
            )
        state.pending_confirmation = True
        self.sessions.save_state(state)
        self.sessions.add_turn(state.session_id, "user", user_goal)
        self.sessions.add_turn(state.session_id, "assistant", state.final_answer or "")
        state.summary = str(self.sessions.get_context(state.session_id)["summary"])
        self.sessions.save_state(state)
        self.sessions.record_trace(trace_id, "agent.waiting_confirmation", {"session_id": state.session_id})
        return state

    def confirm(self, session_id: str, confirm: bool, trace_id: str | None = None) -> AgentStateModel:
        state = self.sessions.get_state(session_id)
        trace_id = trace_id or state.trace_id
        if not state.pending_confirmation:
            return state
        if not confirm:
            state.pending_confirmation = False
            state.final_answer = (state.final_answer or "") + "\n\n未保存笔记。"
            self.sessions.save_state(state)
            self.sessions.record_trace(trace_id, "agent.note.declined", {"session_id": session_id})
            return state
        title = f"排查笔记-{state.user_goal[:40]}"
        result = self._execute_tool(
            "save_note",
            {
                "title": title,
                "content": state.final_answer or "",
                "session_id": state.session_id,
                "confirmed": True,
            },
            trace_id,
        )
        state.tool_results.append(result)
        if result.get("ok"):
            state.note_path = str(result["data"]["path"])
            state.pending_confirmation = False
            state.completed_steps.append("save_note")
            state.final_answer = (state.final_answer or "") + f"\n\n笔记已保存：{state.note_path}"
            self.sessions.record_trace(trace_id, "agent.note.saved", {"session_id": session_id})
        else:
            state.error = str(result.get("error", "笔记保存失败"))
            self.sessions.record_trace(trace_id, "agent.note.failed", {"session_id": session_id})
        self.sessions.save_state(state)
        return state
