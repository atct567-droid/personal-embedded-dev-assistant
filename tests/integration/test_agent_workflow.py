from pathlib import Path
from app.agent.policy import AgentPolicy
from app.agent.workflow import AgentWorkflow
from app.domain.errors import ToolTimeoutError
from app.config import Settings
from app.runtime import ApplicationRuntime


def _runtime(tmp_path: Path) -> ApplicationRuntime:
    settings = Settings.from_root(tmp_path)
    settings.ensure_directories()
    source = settings.inbox_dir / "uart.md"
    source.write_text("# UART\nPA9 作为 TX。", encoding="utf-8")
    log = settings.logs_dir / "device.log"
    log.write_text("INFO boot\nERROR uart timeout\ntoken=secret\n", encoding="utf-8")
    runtime = ApplicationRuntime.from_settings(settings)
    runtime.indexer.ingest_file(source, relative_path="uart.md")
    return runtime


def test_agent_runs_bounded_plan_and_waits_before_saving(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    state = runtime.agent.run("分析 UART ERROR timeout 并检查 PA9")
    assert len(state.current_plan) == 4
    assert len(state.completed_steps) == 3
    assert {step.step_id for step in state.current_plan[:3]} == set(state.completed_steps)
    assert state.pending_confirmation is True
    assert not list(runtime.settings.notes_dir.glob("*.md"))
    assert any(item["tool"] == "search_log" for item in state.tool_results)
    assert all("secret" not in str(item) for item in state.tool_results)
    assert state.log_evidence
    assert state.log_evidence[0].evidence_id in state.final_answer
    checklist_result = next(
        item for item in state.tool_results if item["tool"] == "generate_checklist"
    )
    assert any(
        citation["chunk_id"].startswith("log:")
        for item in checklist_result["data"]["checklist"]
        for citation in item["citations"]
    )

    declined = runtime.agent.confirm(state.session_id, False)
    assert declined.pending_confirmation is False
    assert not list(runtime.settings.notes_dir.glob("*.md"))


def test_agent_confirmation_saves_once(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    state = runtime.agent.run("检查 PA9 UART")
    saved = runtime.agent.confirm(state.session_id, True)
    assert saved.pending_confirmation is False
    assert saved.note_path
    note = runtime.settings.notes_dir / saved.note_path
    assert note.is_file()
    assert "笔记已保存" in saved.final_answer


def test_tool_timeout_retries_at_most_once(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    original_execute = runtime.agent.registry.execute

    def slow_execute(tool_name, arguments, *, deadline_monotonic=None):
        if tool_name == "search_log":
            raise ToolTimeoutError()
        return original_execute(
            tool_name, arguments, deadline_monotonic=deadline_monotonic
        )

    runtime.agent.registry.execute = slow_execute
    workflow = AgentWorkflow(
        runtime.agent.registry,
        runtime.sessions,
        AgentPolicy(max_steps=4, max_retries=1, timeout_seconds=0.001),
    )
    state = workflow.run("检查 UART timeout")
    log_result = next(item for item in state.tool_results if item["tool"] == "search_log")
    assert log_result["ok"] is False
    assert log_result["attempts"] == 2
    assert log_result["error"] == "工具执行超时"
