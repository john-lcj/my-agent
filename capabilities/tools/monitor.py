"""主动监控能力 —— 让 agent 设个"哨兵":盯 URL/文件,变化就自动触发任务。

monitor.create  新建监控(source + 变化时要做什么)
monitor.list    列出现有监控
monitor.delete  删除监控
后台守护(server)按 interval 轮询、比对指纹,变了就把 action 投进任务队列执行。
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _store(ctx: Any):
    return getattr(ctx, "monitors", None)


class MonitorCreate(Tool):
    name = "monitor.create"
    risk = Risk.WRITE  # 建立常驻规则,Chat 需确认
    description = ("新建一个监控:盯住某个 URL 或工作区文件,内容一变就自动执行你指定的任务。"
                  "适合『盯着某页面/某文件,有更新就提醒我/处理』这类需求。")
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "监控名"},
            "source_type": {"type": "string", "description": "url 或 file,默认 url"},
            "source": {"type": "string", "description": "要盯的 URL 或工作区文件路径"},
            "action": {"type": "string", "description": "内容变化时要做的事(给 Captain 的指令)"},
            "interval_sec": {"type": "integer", "description": "检查间隔秒,默认 1800(30 分钟),最小 60"},
        },
        "required": ["source", "action"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置监控存储")
        source = str(args.get("source", "")).strip()
        action = str(args.get("action", "")).strip()
        if not source or not action:
            return CapabilityResult(ok=False, error="需要 source 和 action")
        rec = st.create(
            name=str(args.get("name", "")).strip(),
            source_type=str(args.get("source_type", "url")).strip() or "url",
            source=source, action=action,
            interval_sec=int(args.get("interval_sec", 1800) or 1800))
        return CapabilityResult(ok=True,
            output=f"已建监控「{rec['name']}」(每 {rec['interval_sec']}s 查一次 {source})。变化时自动执行。")


class MonitorList(Tool):
    name = "monitor.list"
    risk = Risk.READ
    description = "列出所有监控器(盯什么、多久查一次、变化时做什么)。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置监控存储")
        rows = st.list()
        if not rows:
            return CapabilityResult(ok=True, output="(暂无监控)")
        lines = [f"- [{r['id']}] {r['name']}:盯 {r['source']}(每 {r['interval_sec']}s)→ {r['action'][:40]}"
                 for r in rows]
        return CapabilityResult(ok=True, output="\n".join(lines))


class MonitorDelete(Tool):
    name = "monitor.delete"
    risk = Risk.WRITE
    description = "按 id 删除一个监控器。"
    schema = {"type": "object",
              "properties": {"id": {"type": "string", "description": "监控 id"}},
              "required": ["id"]}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置监控存储")
        ok = st.delete(str(args.get("id", "")).strip())
        return CapabilityResult(ok=ok, output="已删除" if ok else "未找到该监控")
