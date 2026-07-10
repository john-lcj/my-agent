"""Model-independent task outcome accounting."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    DELIVERY_FAILED = "delivery_failed"


@dataclass
class RunOutcome:
    status: str = TaskStatus.SUCCEEDED.value
    successful_actions: int = 0
    failed_actions: int = 0
    blocked_actions: int = 0
    reason: str = ""
    _forced: bool = False

    def action_succeeded(self) -> None:
        self.successful_actions += 1

    def action_failed(self, reason: str = "") -> None:
        self.failed_actions += 1
        if reason:
            self.reason = reason[:1000]

    def action_blocked(self, reason: str = "") -> None:
        self.blocked_actions += 1
        if reason:
            self.reason = reason[:1000]

    def stop(self, status: str, reason: str = "") -> None:
        if status not in {s.value for s in TaskStatus if s != TaskStatus.DELIVERY_FAILED}:
            raise ValueError(f"invalid execution status: {status}")
        self.status = status
        self.reason = (reason or self.reason)[:1000]
        self._forced = True

    def finalize(self) -> str:
        if self._forced:
            return self.status
        if self.failed_actions:
            self.status = (
                TaskStatus.PARTIAL.value
                if self.successful_actions
                else TaskStatus.FAILED.value
            )
        elif self.blocked_actions:
            self.status = (
                TaskStatus.PARTIAL.value
                if self.successful_actions
                else TaskStatus.BLOCKED.value
            )
        else:
            self.status = TaskStatus.SUCCEEDED.value
        return self.status


@dataclass(frozen=True)
class TaskExecutionResult:
    status: str
    output: str = ""
    error: str = ""

    @classmethod
    def succeeded(cls, output: str = "") -> "TaskExecutionResult":
        return cls(TaskStatus.SUCCEEDED.value, output=output)


def normalize_execution_result(value) -> TaskExecutionResult:
    if isinstance(value, TaskExecutionResult):
        return value
    return TaskExecutionResult.succeeded(str(value or ""))
