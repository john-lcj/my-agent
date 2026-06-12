"""MockLLM —— 无需任何 API key 即可跑通整个 agent 闭环。

它不是真模型,而是一套极简的规则解析器,目的有二:
1. 让你在没有 key 的情况下就能端到端验证"循环 + 治理 + 工具 + 记忆"是否打通。
2. 作为 eval / 单元测试的确定性替身(真模型不确定,没法做回归)。

支持的"指令语法"(直接在对话里输入):
    读 <path>            / read <path>        -> 调用 fs.read
    写 <path> :: <内容>  / write <path> :: .. -> 调用 fs.write
    跑 <命令>            / run <命令>         -> 调用 shell.run
    其他任何输入                               -> 直接当作最终回复回显
"""
from __future__ import annotations

from typing import Optional

from core.types import CapabilityCall, Message, Risk, Role, Step
from llm.streaming import EmitTokenFn, emit_text_chunks


class MockLLM:
    name = "mock"

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[EmitTokenFn] = None,
    ) -> Step:
        # 若上一条是工具结果,说明一次能力调用刚完成 —— 收尾给用户一句话。
        last = messages[-1] if messages else None
        if last is not None and last.role == Role.TOOL:
            text = f"[mock] 已完成,工具返回:\n{last.content}"
            await emit_text_chunks(text, emit_token)
            return Step(text=text)
        # 若上一条是系统消息(被治理拒绝/用户拒绝),停止重试,如实收尾。
        if last is not None and last.role == Role.SYSTEM:
            text = f"[mock] 该动作未执行:{last.content}"
            await emit_text_chunks(text, emit_token)
            return Step(text=text)

        # 取最近一条用户消息来解析指令。
        user_text = ""
        for m in reversed(messages):
            if m.role == Role.USER:
                user_text = m.content.strip()
                break

        call = self._parse(user_text)
        if call is not None:
            return Step(call=call)

        text = (
            f"[mock] 我收到了:{user_text!r}。"
            "(输入 '读 <路径>'、'写 <路径> :: <内容>'、'跑 <命令>' 试试能力调用)"
        )
        await emit_text_chunks(text, emit_token)
        return Step(text=text)

    async def summarize(self, text: str) -> str:
        # 确定性摘要(供回归测试):取前若干行,标注已压缩。
        head = " / ".join(line.strip() for line in text.splitlines() if line.strip())[:200]
        return f"(mock摘要) {head}"

    @staticmethod
    def _parse(text: str) -> CapabilityCall | None:
        lowered = text.lower()
        for prefix in ("读 ", "read "):
            if text.startswith(prefix) or lowered.startswith(prefix):
                path = text[len(prefix):].strip()
                return CapabilityCall(
                    name="fs.read", args={"path": path},
                    intent="用户请求读取文件", declared_risk=Risk.READ,
                )
        for prefix in ("写 ", "write "):
            if text.startswith(prefix) or lowered.startswith(prefix):
                body = text[len(prefix):]
                path, _, content = body.partition("::")
                return CapabilityCall(
                    name="fs.write",
                    args={"path": path.strip(), "content": content.strip()},
                    intent="用户请求写入文件", declared_risk=Risk.WRITE,
                )
        for prefix in ("跑 ", "run "):
            if text.startswith(prefix) or lowered.startswith(prefix):
                cmd = text[len(prefix):].strip()
                return CapabilityCall(
                    name="shell.run", args={"command": cmd},
                    intent="用户请求执行命令", declared_risk=Risk.DESTRUCTIVE,
                )
        return None
