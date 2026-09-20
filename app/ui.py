"""Local Streamlit interface for project-isolated RAG and Agent sessions."""

from __future__ import annotations

from uuid import uuid4

import streamlit as st

from app.domain.errors import AppError
from app.runtime import get_runtime


@st.cache_resource
def runtime():
    return get_runtime()


def _trace_id() -> str:
    return f"trace-ui-{uuid4().hex}"


def _show_error(exc: Exception, trace_id: str) -> None:
    message = exc.public_message if isinstance(exc, AppError) else "操作失败，请根据 trace 查询日志"
    st.error(f"{message}（trace: {trace_id}）")


def main() -> None:
    st.set_page_config(page_title="嵌入式研发助手", layout="wide")
    st.title("个人嵌入式研发知识与故障排查助手")
    st.caption("默认使用本地 SQLite、确定性 Mock Embedding 和 Mock LLM；回答必须显示证据。")
    trace_id = _trace_id()
    try:
        app_runtime = runtime()
    except Exception as exc:
        _show_error(exc, trace_id)
        return

    project_id = st.sidebar.text_input("项目 ID", value="default", max_chars=80).strip() or "default"
    previous_project = st.session_state.get("active_project_id")
    if previous_project != project_id:
        st.session_state["active_project_id"] = project_id
        st.session_state.pop("rag_session_id", None)
        st.session_state.pop("agent_state", None)
    allow_external = st.sidebar.checkbox(
        "允许本次资料发送到远程模型",
        value=False,
        help="还必须同时配置 PDA_ALLOW_REMOTE_MODELS=true；默认禁止外发。",
    )
    if allow_external:
        st.sidebar.warning("仅对确认不含敏感信息的资料启用。")

    rag_tab, agent_tab = st.tabs(["知识库问答", "故障排查 Agent"])
    with rag_tab:
        st.subheader("导入资料")
        uploaded = st.file_uploader(
            "选择 Markdown、TXT、PDF、C/H 或日志文件",
            type=["md", "txt", "pdf", "c", "h", "log"],
        )
        if uploaded is not None and st.button("导入并建立索引", key="ingest-upload"):
            trace_id = _trace_id()
            try:
                result = app_runtime.imports.save_upload_and_ingest(
                    uploaded.name,
                    uploaded.getvalue(),
                    project_id=project_id,
                    allow_external_processing=allow_external,
                )
                st.success(f"{result.status}: {result.source_file}，切片 {result.chunk_count} 个")
            except Exception as exc:
                _show_error(exc, trace_id)
        if st.button("扫描 inbox", key="scan-inbox"):
            trace_id = _trace_id()
            try:
                result = app_runtime.imports.scan(
                    project_id=project_id,
                    allow_external_processing=allow_external,
                )
                st.success(
                    f"新增/更新 {result['indexed']}，未变化 {result['unchanged']}，失败 {result['failed']}"
                )
            except Exception as exc:
                _show_error(exc, trace_id)

        st.subheader("查询")
        question = st.text_area("问题", placeholder="例如：PA9 在 UART 初始化中承担什么角色？")
        if st.button("查询知识库", key="rag-query") and question.strip():
            trace_id = _trace_id()
            try:
                response = app_runtime.conversations.query(
                    question.strip(),
                    project_id=project_id,
                    top_k=5,
                    trace_id=trace_id,
                    session_id=st.session_state.get("rag_session_id"),
                    allow_external_processing=allow_external,
                )
                st.session_state["rag_session_id"] = response.session_id
                st.write(response.answer)
                st.caption(
                    f"置信度：{response.confidence}；session：{response.session_id}；trace：{response.trace_id}"
                )
                for citation in response.citations:
                    st.info(
                        f"来源：{citation.source_file} / {citation.section or '未命名章节'} "
                        f"/ chunk {citation.chunk_id} / score {citation.score:.3f}"
                    )
            except Exception as exc:
                _show_error(exc, trace_id)

    with agent_tab:
        st.subheader("受控故障排查")
        goal = st.text_area("故障目标", placeholder="例如：分析 UART ERROR timeout，并给出排查步骤")
        if st.button("运行排查计划", key="agent-run") and goal.strip():
            trace_id = _trace_id()
            try:
                previous_state = st.session_state.get("agent_state")
                state = app_runtime.agent.run(
                    goal.strip(),
                    project_id=project_id,
                    trace_id=trace_id,
                    session_id=previous_state.session_id if previous_state else None,
                    allow_external_processing=allow_external,
                )
                st.session_state["agent_state"] = state
            except Exception as exc:
                _show_error(exc, trace_id)
        state = st.session_state.get("agent_state")
        if state is not None:
            st.write("计划：")
            for index, step in enumerate(state.current_plan, start=1):
                marker = "✓" if step.step_id in state.completed_steps else "·"
                st.write(f"{marker} {index}. {step.label}")
            st.write(state.final_answer or "")
            st.caption(f"session：{state.session_id}；trace：{state.trace_id}")
            if state.pending_confirmation:
                st.warning("是否把当前排查结果保存到本地笔记？")
                if st.button("确认保存笔记", key="agent-confirm-yes"):
                    try:
                        st.session_state["agent_state"] = app_runtime.agent.confirm(
                            state.session_id, True, trace_id=_trace_id()
                        )
                        st.rerun()
                    except Exception as exc:
                        _show_error(exc, _trace_id())
                if st.button("不保存", key="agent-confirm-no"):
                    try:
                        st.session_state["agent_state"] = app_runtime.agent.confirm(
                            state.session_id, False, trace_id=_trace_id()
                        )
                        st.rerun()
                    except Exception as exc:
                        _show_error(exc, _trace_id())


if __name__ == "__main__":
    main()
