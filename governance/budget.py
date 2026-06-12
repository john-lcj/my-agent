"""预算与轮数守卫 —— 多 agent / 长任务的"刹车"。

多 agent 圆桌烧 token 是指数级的(N agent × M 轮 × 互读上下文),
必须有守卫:最大步数 / token 上限 / 金额上限。超限自动停。

token 计数策略(精确度由高到低,自动降级):
  1. tiktoken 精确计数(DeepSeek/OpenAI 用 cl100k_base;Claude 用 p50k_base 近似)
  2. 字符数 / 3 近似(tiktoken 不可用时的兜底)

金额上限:按 provider 配置每千 token 单价(USD),默认 DeepSeek chat 价格。
主循环在每次 LLM 返回后调用 charge(text, provider),单步完成统一上报。
"""
from __future__ import annotations

from typing import Optional


# ── Token 计数 ─────────────────────────────────────────────────────────────────

_TIKTOKEN_ENCODERS: dict[str, object] = {}   # 懒加载缓存


def _count_tokens(text: str, provider: str = "deepseek") -> int:
    try:
        import tiktoken
        enc_name = "cl100k_base"          # DeepSeek / OpenAI GPT-4 系列
        if provider == "claude":
            enc_name = "p50k_base"        # Claude 的 tokenizer 未公开,用近似值
        enc = _TIKTOKEN_ENCODERS.get(enc_name)
        if enc is None:
            enc = tiktoken.get_encoding(enc_name)
            _TIKTOKEN_ENCODERS[enc_name] = enc
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 3)     # 兜底:字符数 / 3


# ── 单价表(USD / 1K tokens,输出端单价,按需更新)──────────────────────────────

_PRICE_PER_1K: dict[str, float] = {
    "deepseek":   0.00028,    # deepseek-chat output
    "openai":     0.00060,    # gpt-4o-mini output
    "claude":     0.01500,    # claude-sonnet-4 output
    "mock":       0.0,
    "router":     0.00028,    # 路由器按默认 provider 估算
}


# ── BudgetGovernor ─────────────────────────────────────────────────────────────

class BudgetGovernor:
    def __init__(
        self,
        max_steps: int = 20,
        max_tokens: Optional[int] = None,
        max_cost_usd: Optional[float] = None,
        provider: str = "deepseek",
    ) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.provider = provider
        self._steps = 0
        self._tokens = 0
        self._cost_usd = 0.0

    def reset(self) -> None:
        self._steps = 0
        self._tokens = 0
        self._cost_usd = 0.0

    def charge_step(self) -> None:
        self._steps += 1

    def add_tokens(self, n: int) -> None:
        self._tokens += n
        price = _PRICE_PER_1K.get(self.provider, 0.0)
        self._cost_usd += n * price / 1000.0

    def charge(self, text: str, provider: Optional[str] = None) -> int:
        """计算并累加一段文本的 token 消耗,返回本次 token 数。"""
        n = _count_tokens(text, provider or self.provider)
        self.add_tokens(n)
        return n

    def exceeded(self) -> bool:
        if self._steps >= self.max_steps:
            return True
        if self.max_tokens is not None and self._tokens >= self.max_tokens:
            return True
        if self.max_cost_usd is not None and self._cost_usd >= self.max_cost_usd:
            return True
        return False

    def reason(self) -> str:
        if self._steps >= self.max_steps:
            return f"达到最大步数上限({self.max_steps})"
        if self.max_tokens is not None and self._tokens >= self.max_tokens:
            return f"达到 token 预算上限({self.max_tokens:,})"
        if self.max_cost_usd is not None and self._cost_usd >= self.max_cost_usd:
            return f"达到金额上限(${self.max_cost_usd:.4f}),已消耗 ${self._cost_usd:.4f}"
        return ""

    def summary(self) -> str:
        return (f"步数={self._steps}/{self.max_steps}  "
                f"tokens={self._tokens:,}  "
                f"cost=${self._cost_usd:.5f}")

    # ── 只读属性,方便外部观测 ──
    @property
    def tokens(self) -> int:
        return self._tokens

    @property
    def cost_usd(self) -> float:
        return self._cost_usd
