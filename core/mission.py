"""Mission 领域对象 —— "数字员工"持有的工作单元(不是一次对话,而是一个任务)。

一个 Mission 围绕一个目标长期存在,有生命周期状态、子任务清单、产物、通知记录。
单 agent 顺序推进它:执行 → 卡住(缺资料/需授权/需决策)→ 发通知挂起 → 用户回应 → 恢复 → 交付。

这里只放"纯领域逻辑":状态枚举 + 合法转移 + 注意力等级。持久化在 memory/mission_store.py,
执行编排(daemon 推进、邮件中断/恢复)在更上层接线——领域对象本身不依赖它们,便于单测。
"""
from __future__ import annotations

from enum import Enum


class MissionStatus(str, Enum):
    CREATED = "created"          # 刚创建,还没规划
    PLANNING = "planning"        # 正在拆解成子任务
    EXECUTING = "executing"      # 正在顺序执行子任务
    BLOCKED = "blocked"          # 卡住:缺资料/需授权/需付款(等外部条件)
    WAITING_USER = "waiting_user"  # 等用户决策(版本 A/B 之类)
    COMPLETED = "completed"      # 全部完成(终态)
    FAILED = "failed"            # 失败放弃(终态)
    CANCELLED = "cancelled"      # 用户取消(终态)


_TERMINAL = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}

# 合法状态转移:像项目经理一样,不允许乱跳(防状态机被写花)。
_ALLOWED: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.CREATED: {MissionStatus.PLANNING, MissionStatus.CANCELLED},
    MissionStatus.PLANNING: {MissionStatus.EXECUTING, MissionStatus.BLOCKED,
                             MissionStatus.WAITING_USER, MissionStatus.FAILED,
                             MissionStatus.CANCELLED},
    MissionStatus.EXECUTING: {MissionStatus.EXECUTING, MissionStatus.BLOCKED,
                              MissionStatus.WAITING_USER, MissionStatus.COMPLETED,
                              MissionStatus.FAILED, MissionStatus.CANCELLED},
    MissionStatus.BLOCKED: {MissionStatus.EXECUTING, MissionStatus.WAITING_USER,
                            MissionStatus.CANCELLED, MissionStatus.FAILED},
    MissionStatus.WAITING_USER: {MissionStatus.EXECUTING, MissionStatus.BLOCKED,
                                 MissionStatus.CANCELLED, MissionStatus.FAILED},
    MissionStatus.COMPLETED: set(),
    MissionStatus.FAILED: set(),
    MissionStatus.CANCELLED: set(),
}


def is_terminal(status: MissionStatus | str) -> bool:
    return MissionStatus(status) in _TERMINAL


def can_transition(src: MissionStatus | str, dst: MissionStatus | str) -> bool:
    """src→dst 是否合法转移(同态自转 EXECUTING→EXECUTING 表示推进进度,允许)。"""
    src, dst = MissionStatus(src), MissionStatus(dst)
    return dst in _ALLOWED.get(src, set())


class AttentionLevel(int, Enum):
    """注意力治理:决定一个需要关注的事项,该用多重的方式打扰用户。

    这是和"动作风险分级"正交的另一维度——管的不是"能不能做",而是"要不要烦你、烦多重"。
    """
    AUTO = 0       # 自己决定,不打扰
    NOTIFY = 1     # 轻通知(Slack/应用内),不阻塞
    EMAIL = 2      # 邮件告知/请求,通常挂起等回应
    CONFIRM = 3    # 必须用户明确确认才继续(阻塞)
    STOP = 4       # 禁止继续(硬停)


def attention_action(level: AttentionLevel | int) -> str:
    """把注意力等级翻译成执行动作:auto(继续)/ notify(通知不停)/ block(挂起等人)/ stop(终止)。"""
    level = AttentionLevel(level)
    if level == AttentionLevel.AUTO:
        return "auto"
    if level == AttentionLevel.NOTIFY:
        return "notify"
    if level in (AttentionLevel.EMAIL, AttentionLevel.CONFIRM):
        return "block"
    return "stop"
