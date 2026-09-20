"""Stable, non-sensitive application errors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    code: str
    public_message: str
    status_code: int = 400

    def __post_init__(self) -> None:
        Exception.__init__(self, self.public_message)


class InvalidInputError(AppError):
    def __init__(self, message: str = "请求参数无效") -> None:
        super().__init__("INVALID_INPUT", message, 422)


class PathPolicyError(AppError):
    def __init__(self, message: str = "路径不在允许的工作目录内") -> None:
        super().__init__("PATH_NOT_ALLOWED", message, 400)


class FilePolicyError(AppError):
    def __init__(self, message: str = "文件不符合导入策略") -> None:
        super().__init__("FILE_NOT_ALLOWED", message, 400)


class DependencyUnavailableError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("DEPENDENCY_UNAVAILABLE", message, 503)


class NotFoundError(AppError):
    def __init__(self, message: str = "请求的资源不存在") -> None:
        super().__init__("NOT_FOUND", message, 404)


class PolicyDeniedError(AppError):
    def __init__(self, message: str = "操作被安全策略拒绝") -> None:
        super().__init__("POLICY_DENIED", message, 403)


class StorageError(AppError):
    def __init__(self, message: str = "本地存储操作失败") -> None:
        super().__init__("STORAGE_ERROR", message, 500)


class ToolTimeoutError(AppError):
    def __init__(self, message: str = "工具执行超时") -> None:
        super().__init__("TOOL_TIMEOUT", message, 408)
