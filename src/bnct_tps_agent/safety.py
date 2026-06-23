from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    CLINICAL = "clinical"


class PolicyDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


ApprovalCallback = Callable[[str, Risk, dict], bool]


class SafetyPolicy:
    def __init__(self, approval_callback: ApprovalCallback | None = None):
        self.approval_callback = approval_callback

    def decide(self, tool_name: str, risk: Risk, arguments: dict) -> Decision:
        if risk is Risk.CLINICAL:
            return Decision(
                False,
                "临床动作被硬性阻断：Agent 不能批准计划、修改处方或写回患者数据。",
            )
        if risk is Risk.READ:
            return Decision(True, "只读工具自动允许")
        if self.approval_callback is None:
            return Decision(False, "该工具需要人工批准，但当前会话不可交互")
        approved = self.approval_callback(tool_name, risk, arguments)
        return Decision(approved, "用户已批准" if approved else "用户拒绝批准")

    def require(self, tool_name: str, risk: Risk, arguments: dict) -> None:
        decision = self.decide(tool_name, risk, arguments)
        if not decision.allowed:
            raise PolicyDenied(decision.reason)

