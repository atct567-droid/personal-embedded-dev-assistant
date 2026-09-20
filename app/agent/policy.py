"""Conservative execution policy for the troubleshooting agent."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import PolicyDeniedError


ALLOWED_TOOLS = frozenset({"search_knowledge", "search_log", "generate_checklist", "save_note"})


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    max_steps: int = 4
    max_retries: int = 1
    timeout_seconds: float = 5.0

    def validate_tool(self, tool_name: str) -> None:
        if tool_name not in ALLOWED_TOOLS:
            raise PolicyDeniedError("工具不在允许列表内")

    def validate_step(self, completed_steps: int) -> None:
        if completed_steps >= self.max_steps:
            raise PolicyDeniedError("Agent 已达到最大步数")

