"""每日简报 —— 一个每天主动找主人的 agent,而不是等主人打开网页。

实现方式:复用 scheduler 的"到点跑一句 prompt + 投递结果"管线,本模块只负责:
  1. 简报 prompt 模板(指导无人值守 agent 用只读能力汇总信息);
  2. 服务启动时幂等注册 daily 定时任务(已存在同名任务则不动,尊重用户在 UI 里的修改)。

投递渠道/时间由 .env 配置(AGENT_BRIEFING_*),也可在 Web 定时任务页直接改。
"""
from __future__ import annotations

BRIEFING_TASK_NAME = "每日简报"

BRIEFING_PROMPT = """请为主人生成今天的每日简报。你只有只读能力(检索记忆/读文件/联网搜索),按以下结构汇总:

【待办与未尽事项】用 memory.recall 检索「待办」「未完成」「计划」「下次」等关键词,提炼最多 3 条;确无记录则写"暂无"。
【近期要点】用 memory.recall 检索最近的工作与对话要点,提炼 2-3 条。
【今日建议】结合以上,给 1-2 条具体可行动的建议。

要求:总长 300 字以内,口吻亲切自然,条目化,可直接作为消息推送;不要暴露工具调用细节。"""


# 已移除的旧渠道:历史任务若仍投递到这些渠道,自动迁移为邮件,避免投递失败。
_REMOVED_CHANNELS = {"qq", "wechat", "slack", "telegram", "onebot"}


def ensure_briefing_task(store, *, at_hhmm: str, channel: str, to: str = "") -> bool:
    """幂等注册每日简报任务。已存在同名任务则跳过(返回 False),新建返回 True。"""
    for t in store.list():
        if t.name == BRIEFING_TASK_NAME:
            # 迁移:旧任务投递到已删除渠道 → 改为邮件(发给自己)
            if getattr(t, "deliver", "") in _REMOVED_CHANNELS:
                t.deliver = "email"
                t.deliver_to = ""
                store.save(t)
            return False
    if not channel or channel == "none":
        deliver = "none"
    else:
        deliver = channel
    store.create(
        name=BRIEFING_TASK_NAME,
        prompt=BRIEFING_PROMPT,
        schedule_type="daily",
        at_hhmm=at_hhmm or "08:00",
        deliver=deliver,
        deliver_to=to,
        task_type="agent",
    )
    return True
