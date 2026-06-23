"""失败回退 LLM —— 主模型出错/超时时,自动切到备用模型链。

单模型(如 DeepSeek)偶发连接错误/超时/限流时,整轮就失败了。本包装器把
"主模型 + 若干备用模型"串成一条链:主模型抛异常 → 退到下一个,直到成功或全部用尽。
对 agent 透明(仍是 LLM 接口),按需配置即可显著提升长任务成功率。

配置:环境变量 AGENT_FALLBACK_MODELS="deepseek-v4-pro,claude-haiku"(逗号分隔的备用 model id)。
"""
from __future__ import annotations

from typing import Optional

from core.types import Message, Step


class FallbackLLM:
    def __init__(self, primary, backups: list) -> None:
        self._chain = [primary] + [b for b in backups if b is not None]
        self.name = getattr(primary, "name", "fallback")

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[object] = None,
    ) -> Step:
        last: Exception | None = None
        for i, llm in enumerate(self._chain):
            try:
                # 只让主模型流式输出,避免回退后把同一段文字重复推送。
                return await llm.next_step(messages, capabilities, emit_token if i == 0 else None)
            except Exception as e:  # noqa: BLE001 —— 任何失败都尝试下一个模型
                last = e
                nxt = self._chain[i + 1] if i + 1 < len(self._chain) else None
                print(f"[fallback] 模型 {getattr(llm, 'name', '?')} 失败:{e};"
                      + (f"切换到 {getattr(nxt, 'name', '?')}" if nxt else "已无备用模型"))
        assert last is not None
        raise last
