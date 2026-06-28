"""功能门控 — 根据授权状态决定哪些能力可用。

Free 限制:
  - 每日对话上限 100 条
  - skill 插件禁用
  - 定时任务禁用
  - 监控任务禁用
  - shell.run 禁用（最敏感的本地能力）
  - browser.* 禁用

Pro 全解锁，无限制。

使用方式:
  from license_client.gates import get_gates
  gates = get_gates()          # 从全局缓存读，不联网
  if not gates.allow_shell:
      raise FeatureGated("shell 需要 Pro 授权")
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .client import LicenseStatus


@dataclass
class FeatureGates:
    plan:           str
    valid:          bool
    allow_skill:    bool   # skill 插件
    allow_shell:    bool   # shell.run
    allow_browser:  bool   # browser.*
    allow_schedule: bool   # 定时任务
    allow_monitor:  bool   # 监控任务
    allow_gui:      bool   # gui.*
    daily_msg_limit: Optional[int]   # None = 无限

    @property
    def is_pro(self) -> bool:
        return self.plan == "pro" and self.valid

    def check(self, capability: str) -> bool:
        """判断某个 capability 前缀是否允许。"""
        if self.is_pro:
            return True
        if capability.startswith("shell.") or capability == "shell":
            return self.allow_shell
        if capability.startswith("skill.") or capability == "skill":
            return self.allow_skill
        if capability.startswith("browser."):
            return self.allow_browser
        if capability.startswith("gui."):
            return self.allow_gui
        return True   # 其余能力 free 可用


def make_gates(status: LicenseStatus) -> FeatureGates:
    if status.is_pro:
        return FeatureGates(
            plan="pro", valid=True,
            allow_skill=True, allow_shell=True, allow_browser=True,
            allow_schedule=True, allow_monitor=True, allow_gui=True,
            daily_msg_limit=None,
        )
    # Free 或未激活
    return FeatureGates(
        plan=status.plan, valid=status.valid,
        allow_skill=False, allow_shell=False, allow_browser=False,
        allow_schedule=False, allow_monitor=False, allow_gui=False,
        daily_msg_limit=100,
    )


# ── 全局单例（启动时初始化一次）─────────────────────────────────────────────
_gates: Optional[FeatureGates] = None


def init_gates(status: LicenseStatus) -> FeatureGates:
    global _gates
    _gates = make_gates(status)
    return _gates


def get_gates() -> FeatureGates:
    """获取当前功能门控，未初始化时返回最严格的 free 门控。"""
    if _gates is None:
        return make_gates(LicenseStatus(valid=False, plan="free"))
    return _gates
