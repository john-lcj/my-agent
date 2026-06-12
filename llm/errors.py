"""LLM 调用异常 → 用户可读说明。"""
from __future__ import annotations


def format_llm_error(exc: Exception) -> str:
    msg = str(exc)
    cls = type(exc).__name__
    low = msg.lower()
    if cls == "AuthenticationError" or "401" in msg or "api key" in low or "authentication" in low:
        return (
            "模型 API 密钥无效或已过期。请到 https://platform.deepseek.com 检查余额并重新生成 Key, "
            "更新 .env 里的 DEEPSEEK_API_KEY。临时测试可设 AGENT_PROVIDER=mock。"
        )
    if "429" in msg or "rate limit" in low or "quota" in low:
        return "模型请求过于频繁或额度不足,请稍后再试。"
    if "connection" in low or "timeout" in low:
        return f"无法连接模型服务,请检查网络: {msg[:200]}"
    return f"模型调用失败({cls}): {msg[:400]}"
