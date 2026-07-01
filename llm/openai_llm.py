"""OpenAI(及任何 OpenAI 兼容协议)的 LLM 实现。

DeepSeek 复用同一套协议,只是换 base_url 与默认模型(见 deepseek_llm.py)。
这里把三件事在 adapter 内部抹平,不让厂商差异泄露到上层:
- 消息格式转换(我们的 Message -> OpenAI messages)
- 能力 -> tools(function calling)schema
- 返回的 tool_calls -> 统一的 CapabilityCall
- DeepSeek 思考模式 reasoning_content 的捕获与回传
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Optional

from core.context import repair_tool_pairing
from core.types import CapabilityCall, Message, Role, Step
from llm.streaming import EmitTokenFn

# 瞬时错误关键词(超时 / 连接 / 限流 / 网关)——这类不应当场失败,应退避重试。
_TRANSIENT = ("timeout", "timed out", "connection", "rate limit", "ratelimit",
              "429", "overloaded", "503", "502", "temporarily")


def _is_transient(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in _TRANSIENT)


async def _acreate_with_retry(client, **kwargs):
    """对 chat.completions.create 做指数退避重试,扛住并发压测下的瞬时超时/连接错误。

    并发跑多个子代理时(map-reduce 并行节点),DeepSeek 偶发超时/连接重置是常态;
    一次抖动就让整个节点失败、级联跳过太脆。这里重试 N 次,显著提升长任务成功率。
    """
    retries = int(os.environ.get("AGENT_LLM_RETRIES", "3"))
    delay = 1.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 —— 需按错误内容判断是否瞬时
            last = e
            if attempt >= retries or not _is_transient(e):
                raise
            await asyncio.sleep(delay + random.uniform(0, 0.4))
            delay = min(delay * 2, 8.0)
    assert last is not None
    raise last


class OpenAILLM:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key_env: str = "OPENAI_API_KEY",
        base_url: Optional[str] = None,
        name: str = "openai",
        api_key: Optional[str] = None,
        api_keys: Optional[list] = None,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url
        # key 池:多个 key 时每次请求轮流用一个,把并发分散到不同 key(绕开单 key 限流)。
        pool = [k for k in (api_keys or []) if k] or ([api_key] if api_key else [])
        self._keys = pool                      # 空 = 回退读环境变量(单 key)
        self._clients: dict = {}               # key -> AsyncOpenAI(懒建)
        self._rr = 0                           # round-robin 游标

    def _pick_client(self):
        try:
            from openai import AsyncOpenAI  # 懒加载,未安装也不影响 mock
        except ImportError as e:
            raise RuntimeError("未安装 openai SDK,请先 `pip install openai`。") from e
        keys = self._keys or [os.environ.get(self.api_key_env) or ""]
        key = keys[self._rr % len(keys)]
        self._rr += 1
        if not key:
            raise RuntimeError(
                f"缺少 {self.api_key_env}(或 key 池为空)。请在 .env 配置,或改用 MockLLM。"
            )
        client = self._clients.get(key)
        if client is None:
            kwargs = {"api_key": key, "base_url": self.base_url}
            if (self.name or "").lower() == "openrouter":
                kwargs["default_headers"] = {
                    "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "https://irestart-your-life.club"),
                    "X-OpenRouter-Title": os.environ.get("OPENROUTER_APP_TITLE", "Captain"),
                }
            client = AsyncOpenAI(**kwargs)
            self._clients[key] = client
        return client

    # 兼容旧调用名
    def _ensure_client(self):
        return self._pick_client()

    def needs_deepseek_reasoning_echo(self) -> bool:
        """DeepSeek 思考模式要求 tool-call 轮次的 reasoning_content 必须回传。"""
        if (self.name or "").lower() == "deepseek":
            return True
        model = (self.model or "").lower()
        if "deepseek" in model:
            return True
        base = (self.base_url or "").lower()
        return "deepseek" in base

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[EmitTokenFn] = None,
    ) -> Step:
        if emit_token is not None:
            return await self._next_step_stream(messages, capabilities, emit_token)
        return await self._next_step_blocking(messages, capabilities)

    async def _next_step_blocking(self, messages: list[Message], capabilities: list[dict]) -> Step:
        client = self._ensure_client()
        name_map = {_sanitize(c["name"]): c["name"] for c in capabilities}
        resp = await _acreate_with_retry(
            client,
            model=self.model,
            messages=_to_openai_messages(
                messages,
                echo_deepseek_reasoning=self.needs_deepseek_reasoning_echo(),
            ),
            tools=_to_openai_tools(capabilities) or None,
        )
        return self._parse_choice(resp.choices[0].message, name_map)

    async def _next_step_stream(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: EmitTokenFn,
    ) -> Step:
        client = self._ensure_client()
        name_map = {_sanitize(c["name"]): c["name"] for c in capabilities}
        stream = await _acreate_with_retry(
            client,
            model=self.model,
            messages=_to_openai_messages(
                messages,
                echo_deepseek_reasoning=self.needs_deepseek_reasoning_echo(),
            ),
            tools=_to_openai_tools(capabilities) or None,
            stream=True,
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        intent_parts: list[str] = []

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
            if delta.content:
                content_parts.append(delta.content)
                if not tool_acc:
                    await emit_token(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            if getattr(delta, "content", None) and tool_acc:
                intent_parts.append(delta.content or "")

        reasoning = "".join(reasoning_parts) or None

        if tool_acc:
            first = tool_acc[min(tool_acc.keys())]
            try:
                args = json.loads(first.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            return Step(
                call=CapabilityCall(
                    name=name_map.get(first.get("name", ""), first.get("name", "")),
                    args=args,
                    intent="".join(intent_parts).strip(),
                    call_id=first.get("id") or "",
                ),
                reasoning_content=reasoning,
            )

        text = "".join(content_parts)
        return Step(text=text, reasoning_content=reasoning)

    @staticmethod
    def _parse_choice(choice, name_map: dict) -> Step:
        reasoning = getattr(choice, "reasoning_content", None)
        if choice.tool_calls:
            tc = choice.tool_calls[0]
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            return Step(
                call=CapabilityCall(
                    name=name_map.get(tc.function.name, tc.function.name),
                    args=args,
                    intent=(choice.content or "").strip(),
                    call_id=tc.id or "",
                ),
                reasoning_content=reasoning,
            )
        return Step(text=choice.content or "", reasoning_content=reasoning)

    async def summarize(self, text: str) -> str:
        """用同一模型把一段对话压缩成简短摘要(供工作记忆压缩调用)。"""
        client = self._ensure_client()
        resp = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content":
                 "把下面的对话压缩成要点摘要,保留关键事实、决定、未完成事项,去掉寒暄。用简体中文,150字以内。"},
                {"role": "user", "content": text},
            ],
        )
        return resp.choices[0].message.content or ""


def _assistant_openai_dict(m: Message, *, echo_deepseek_reasoning: bool) -> dict:
    """序列化 assistant 消息,含 DeepSeek reasoning_content 回传。"""
    if m.tool_calls:
        payload: dict = {
            "role": "assistant",
            "content": m.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": _sanitize(tc.name),
                        "arguments": json.dumps(tc.args, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ],
        }
        if echo_deepseek_reasoning:
            payload["reasoning_content"] = (
                m.reasoning_content if m.reasoning_content is not None else ""
            )
        return payload

    payload = {"role": "assistant", "content": m.content}
    if echo_deepseek_reasoning and m.reasoning_content is not None:
        payload["reasoning_content"] = m.reasoning_content
    return payload


def _to_openai_messages(
    messages: list[Message],
    *,
    echo_deepseek_reasoning: bool = False,
) -> list[dict]:
    """转换为 OpenAI 严格协议:assistant 携带 tool_calls,tool 用 tool_call_id 配对。"""
    out: list[dict] = []
    for m in repair_tool_pairing(messages):
        if m.role == Role.SYSTEM:
            out.append({"role": "system", "content": m.content})
        elif m.role == Role.USER:
            out.append({"role": "user", "content": m.content})
        elif m.role == Role.TOOL:
            out.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id or "0",
                "content": m.content,
            })
        elif m.role == Role.ASSISTANT:
            out.append(_assistant_openai_dict(
                m, echo_deepseek_reasoning=echo_deepseek_reasoning,
            ))
        else:
            out.append({"role": "assistant", "content": m.content})
    return out


def _sanitize(name: str) -> str:
    """把能力名转成 provider 接受的形式(^[a-zA-Z0-9_-]+$)。"""
    return name.replace(".", "_")


def _to_openai_tools(capabilities: list[dict]) -> list[dict]:
    tools = []
    for c in capabilities:
        tools.append({
            "type": "function",
            "function": {
                "name": _sanitize(c["name"]),
                "description": c.get("description", ""),
                "parameters": c.get("schema", {"type": "object", "properties": {}}),
            },
        })
    return tools
