"""模型接入连通性测试 —— 真发一次最小请求,验证"这个接口到底通不通"。

chat/vision:发一条 max_tokens=1 的最小对话补全(真实鉴权 + 真实可达)。
image:走 models.list()(便宜,验证鉴权,不烧生成额度)。
claude:用 anthropic SDK 发最小 messages。
任何异常都转成清晰错误串返回,绝不抛。离线环境会如实返回网络错误。
"""
from __future__ import annotations

import time

__test__ = False


async def test_endpoint(sdk: str, kind: str, base_url: str, api_key: str, model: str) -> dict:
    if not api_key:
        return {"ok": False, "error": "未填 API Key"}
    if not model and kind != "image":
        return {"ok": False, "error": "未填模型名"}
    t0 = time.time()
    try:
        if sdk == "anthropic":
            try:
                from anthropic import AsyncAnthropic
            except ImportError:
                return {"ok": False, "error": "未安装 anthropic SDK(pip install anthropic)"}
            client = AsyncAnthropic(api_key=api_key)
            await client.messages.create(
                model=model, max_tokens=1,
                messages=[{"role": "user", "content": "hi"}])
        else:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                return {"ok": False, "error": "未安装 openai SDK(pip install openai)"}
            client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
            if kind == "image":
                await client.models.list()           # 便宜地验证鉴权
            else:
                await client.chat.completions.create(
                    model=model, max_tokens=1,
                    messages=[{"role": "user", "content": "hi"}])
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "401" in msg or "unauthorized" in low or "invalid_api_key" in low or "authentication" in low:
            hint = "鉴权失败:API Key 不对"
        elif "404" in msg or "not found" in low or "model" in low and "exist" in low:
            hint = "模型名或 base_url 不对(404)"
        elif "connect" in low or "timeout" in low or "resolve" in low or "network" in low:
            hint = "网络连不上该 base_url(检查地址/网络)"
        else:
            hint = "调用失败"
        return {"ok": False, "error": f"{hint}:{msg[:200]}"}
    return {"ok": True, "latency_ms": round((time.time() - t0) * 1000)}
