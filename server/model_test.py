"""模型接入连通性测试 —— 真发一次最小请求,验证"这个接口到底通不通"。

chat/vision:发一条 max_tokens=1 的最小对话补全(真实鉴权 + 真实可达)。
image:走 models.list()(便宜,验证鉴权,不烧生成额度)。
claude:用 anthropic SDK 发最小 messages。
任何异常都转成清晰错误串返回,绝不抛。离线环境会如实返回网络错误。
"""
from __future__ import annotations

import time

from server.model_keys import migrate_mimo_model

__test__ = False


def _is_mimo_url(base_url: str) -> bool:
    return "xiaomimimo.com" in (base_url or "").lower()


def friendly_error_message(error: Exception | str) -> str:
    msg = str(error)
    low = msg.lower()
    if "402" in msg or "insufficient credits" in low or "never purchased credits" in low:
        hint = "账号余额不足或未购买额度:请到对应平台充值/开通 credits 后再测试"
    elif "429" in msg or "rate limit" in low or "too many requests" in low:
        hint = "触发限流:请稍后再试或更换可用额度的 Key"
    elif "403" in msg or "permission" in low or "forbidden" in low:
        hint = "权限不足:该 Key 没有调用此模型的权限"
    elif "401" in msg or "unauthorized" in low or "invalid_api_key" in low or "authentication" in low:
        hint = "鉴权失败:API Key 不对"
    elif "404" in msg or "not found" in low or "model" in low and "exist" in low:
        hint = "模型名或 base_url 不对(404)"
    elif "deprecated" in low or "mimo-v2-omni" in low:
        hint = "模型已下线:请改用 mimo-v2.5-pro(设置页模型名)"
    elif "connect" in low or "timeout" in low or "resolve" in low or "network" in low:
        hint = "网络连不上该 base_url(检查地址/网络)"
    else:
        hint = "调用失败"
    return f"{hint}。原始信息:{msg[:160]}"


async def _test_mimo(base_url: str, api_key: str, model: str) -> None:
    """小米 MiMo 专用:httpx + api-key 头 + max_completion_tokens。"""
    import httpx

    base = (base_url or "https://api.xiaomimimo.com/v1").rstrip("/")
    model = migrate_mimo_model(model)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 8,
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
    r.raise_for_status()


async def test_endpoint(sdk: str, kind: str, base_url: str, api_key: str, model: str) -> dict:
    if not api_key:
        return {"ok": False, "error": "未填 API Key"}
    if not model and kind != "image":
        return {"ok": False, "error": "未填模型名"}
    t0 = time.time()
    try:
        if _is_mimo_url(base_url):
            if kind == "image":
                # 小米无 models.list;走最小 chat 测通
                await _test_mimo(base_url, api_key, model or "mimo-v2.5-pro")
            else:
                await _test_mimo(base_url, api_key, model)
        elif sdk == "anthropic":
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
        return {"ok": False, "error": friendly_error_message(e)}
    return {"ok": True, "latency_ms": round((time.time() - t0) * 1000)}
