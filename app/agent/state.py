"""Agent planning helpers."""

from __future__ import annotations

from app.domain.models import AgentPlanStep, AgentStateModel


def build_plan(user_goal: str) -> list[AgentPlanStep]:
    """Return a fixed, inspectable plan with no hidden tool execution."""
    del user_goal
    return [
        AgentPlanStep(step_id="search_knowledge", label="查询知识库中的相关证据"),
        AgentPlanStep(step_id="search_log", label="搜索允许目录中的相关日志"),
        AgentPlanStep(step_id="generate_checklist", label="根据证据生成结构化排查清单"),
        AgentPlanStep(step_id="save_note", label="等待用户确认是否保存笔记"),
    ]


def new_state(
    session_id: str,
    trace_id: str,
    user_goal: str,
    project_id: str = "default",
) -> AgentStateModel:
    return AgentStateModel(
        session_id=session_id,
        trace_id=trace_id,
        user_goal=user_goal,
        project_id=project_id,
        current_plan=build_plan(user_goal),
    )
